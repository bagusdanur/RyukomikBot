import asyncio
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database
from helpers.chapters import chapter_display, normalize_chapter, parse_chapters
from raw_downloader.retry import get_json
from views.raw_views import filter_allowed_chapters


class ChapterParserTests(unittest.TestCase):
    def test_integer_range(self):
        self.assertEqual(parse_chapters("1-5"), ["1", "2", "3", "4", "5"])
        self.assertEqual(chapter_display(parse_chapters("1-5")), "1-5")

    def test_free_list_and_decimal(self):
        self.assertEqual(parse_chapters("1, 3, 7, 8.5"), ["1", "3", "7", "8.5"])
        self.assertEqual(chapter_display(parse_chapters("1,3,7,8.5")), "1, 3, 7, 8.5")

    def test_invalid_inputs(self):
        for value in ("", "5-1", "1,1", "1,,2", "1-6", "chapter-a"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_chapters(value)

    def test_api_chapter_normalization(self):
        self.assertEqual(normalize_chapter("chapter-8.50"), "8.5")
        self.assertEqual(normalize_chapter("Let's Work - Chapter 3"), "3")

    def test_raw_list_only_contains_assignment_chapters(self):
        source = [
            {"id": "chapter-1", "title": "Chapter 1"},
            {"id": "chapter-2", "title": "Chapter 2"},
            {"id": "chapter-9", "title": "Chapter 9"},
        ]
        filtered, missing = filter_allowed_chapters(source, ["1", "2", "3"])
        self.assertEqual([item["id"] for item in filtered], ["chapter-1", "chapter-2"])
        self.assertEqual(missing, ["3"])


class FakeResponse:
    def __init__(self, status, payload):
        self.status, self.payload = status, payload
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): return False
    async def json(self): return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
    def get(self, *_args, **_kwargs):
        self.calls += 1
        return self.responses.pop(0)


class RawRetryTests(unittest.TestCase):
    def test_first_failure_then_success(self):
        session = FakeSession([
            FakeResponse(503, {}),
            FakeResponse(200, {"images": ["1.jpg", "2.jpg"]}),
        ])
        result = asyncio.run(get_json(session, "https://example.test", source="doujiva", stage="chapter"))
        self.assertEqual(result["images"], ["1.jpg", "2.jpg"])
        self.assertEqual(session.calls, 2)

    def test_permanent_404_is_not_retried(self):
        session = FakeSession([FakeResponse(404, {})])
        self.assertIsNone(asyncio.run(get_json(session, "https://example.test", source="doujiva", stage="chapter")))
        self.assertEqual(session.calls, 1)


class MultiChapterDatabaseTests(unittest.TestCase):
    def test_legacy_assignment_migrates_without_changing_total(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "legacy.db")
            connection = sqlite3.connect(path)
            connection.execute("""CREATE TABLE assignments (
                id INTEGER PRIMARY KEY, manga TEXT, chapter TEXT, staff_id INTEGER, role TEXT,
                base_rate INTEGER, final_rate INTEGER, multiplier REAL, status TEXT,
                gdrive_link TEXT, admin_notes TEXT, message_id INTEGER, ticket_channel_id INTEGER,
                claimed_at TEXT, assigned_at TEXT, submitted_at TEXT, approved_at TEXT, paid_period TEXT
            )""")
            connection.execute("INSERT INTO assignments VALUES (1,'Legacy','10',100,'TS',12000,12000,1,'approved',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)")
            connection.commit()
            connection.close()
            with patch.object(database, "DB_PATH", path):
                asyncio.run(database.setup_database())
            connection = sqlite3.connect(path)
            row = connection.execute("SELECT final_rate,rate_per_chapter,chapter_count,chapters FROM assignments WHERE id=1").fetchone()
            connection.close()
            self.assertEqual(row, (12000, 12000, 1, '["10"]'))

    def test_multi_chapter_total_is_stored_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "new.db")
            with patch.object(database, "DB_PATH", path):
                asyncio.run(database.setup_database())
                assignment_id = asyncio.run(database.create_assignment(
                    manga="Project", chapter="1-5", chapters=["1", "2", "3", "4", "5"],
                    role="TS", base_rate=12000, rate_per_chapter=12000,
                    final_rate=60000, multiplier=1,
                ))
            connection = sqlite3.connect(path)
            row = connection.execute("SELECT final_rate,rate_per_chapter,chapter_count FROM assignments WHERE id=?", (assignment_id,)).fetchone()
            connection.close()
            self.assertEqual(row, (60000, 12000, 5))

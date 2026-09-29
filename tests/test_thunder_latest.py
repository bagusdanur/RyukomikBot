"""Thunderscans "project baru" polling — tanpa network, tanpa Discord.

Penting: semua tes ini memindahkan `database.DB_PATH` ke file sementara
sebelum menyentuh apa pun, lalu mengembalikannya. Tanpa itu tes akan
menulis tabel ke data/ryukomik.db produksi.
"""

import os
import re
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import database
import project_scout as scout


def payload(*slugs, page=1, has_next=False):
    """Bentuk respon /thunder/latest seperti aslinya."""
    return {
        "success": True,
        "source": "en-thunderscans.com",
        "order": "latest",
        "page": page,
        "meta": {"currentPage": page, "totalPages": 2 if has_next else 1,
                 "totalItems": len(slugs), "hasNextPage": has_next},
        "data": [
            {
                "source": "thunder",
                "title": slug.replace("-", " ").title(),
                "slug": slug,
                "detail_link": f"https://en-thunderscans.com/comics/{slug}/",
                "info": "Ongoing",
                "published_at": "2026-09-29T17:24:28.000Z" if i % 2 == 0 else "",
            }
            for i, slug in enumerate(slugs)
        ],
    }


def fetcher(pages):
    """Stand-in for fetch_thunder_latest keyed by page."""
    async def _fetch(page=1):
        return pages.get(page, {})
    return _fetch


@contextmanager
def isolated_db():
    """A throwaway database file, restored on exit."""
    handle, path = tempfile.mkstemp(prefix="thunder-latest-", suffix=".db")
    os.close(handle)
    os.unlink(path)
    original = database.DB_PATH
    database.DB_PATH = path
    try:
        yield path
    finally:
        database.DB_PATH = original
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass


async def seeded_db():
    """Create the scout tables in the isolated database."""
    await scout.setup_scout_tables()


class ThunderRowsTests(unittest.TestCase):
    def test_rows_keeps_order_and_fields(self):
        rows = scout._thunder_rows(payload("alpha-comic", "beta-comic"))
        self.assertEqual([row["slug"] for row in rows], ["alpha-comic", "beta-comic"])
        self.assertEqual(rows[0]["title"], "Alpha Comic")
        self.assertEqual(rows[0]["status"], "Ongoing")
        self.assertTrue(rows[0]["detail_link"].endswith("/comics/alpha-comic/"))

    def test_rows_skips_items_without_slug_or_title(self):
        broken = {"data": [{"title": "No Slug"}, {"slug": "no-title"}, "not-a-dict", {"slug": "ok", "title": "Ok"}]}
        rows = scout._thunder_rows(broken)
        self.assertEqual([row["slug"] for row in rows], ["ok"])

    def test_rows_tolerates_empty_or_malformed_payload(self):
        for broken in ({}, None, [], {"data": None}, {"data": "x"}, {"success": False}):
            with self.subTest(payload=broken):
                self.assertEqual(scout._thunder_rows(broken), [])

    def test_rows_exposes_rss_timestamp_when_feed_covered_the_slug(self):
        rows = scout._thunder_rows(payload("alpha-comic", "beta-comic"))
        self.assertEqual(rows[0]["published_at"], "2026-09-29T17:24:28.000Z")
        self.assertEqual(rows[1]["published_at"], "", "tanpa RSS tetap ada, kosong, bukan hilang")


class PollThunderLatestTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_run_is_a_silent_baseline(self):
        """Poll pertama menyimpan semua judul lama TANPA melapor."""
        with isolated_db():
            await seeded_db()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload("a", "b", "c"))):
                self.assertEqual(await scout.poll_thunder_latest(), [],
                                 "30 judul lama tidak boleh membanjiri channel")
            db = await database.get_db()
            try:
                rows = await (await db.execute("SELECT slug, notified_at FROM thunder_latest_seen ORDER BY slug")).fetchall()
            finally:
                await db.close()
            self.assertEqual([row["slug"] for row in rows], ["a", "b", "c"])
            self.assertTrue(all(row["notified_at"] is None for row in rows),
                            "baseline tidak boleh ditandai sudah dikirim")

    async def test_baseline_covers_every_page_not_just_the_first(self):
        """Judul di halaman 2 ikut baseline supaya tidak dianggap baru nanti."""
        with isolated_db():
            await seeded_db()
            pages = {
                1: payload(*[f"p1-{n}" for n in range(3)], page=1, has_next=True),
                2: payload("p2-one", "p2-two", page=2, has_next=False),
            }
            with patch.object(scout, "fetch_thunder_latest", new=fetcher(pages)):
                self.assertEqual(await scout.poll_thunder_latest(), [])
            db = await database.get_db()
            try:
                slugs = {row["slug"] for row in await (await db.execute(
                    "SELECT slug FROM thunder_latest_seen"
                )).fetchall()}
            finally:
                await db.close()
            self.assertEqual(slugs, {"p1-0", "p1-1", "p1-2", "p2-one", "p2-two"},
                             "halaman 2 wajib ikut baseline")

    async def test_second_run_reports_only_titles_added_since(self):
        with isolated_db():
            await seeded_db()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload("a", "b"))):
                await scout.poll_thunder_latest()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload("c", "a", "b"))):
                events = await scout.poll_thunder_latest()
            self.assertEqual([event["slug"] for event in events], ["c"],
                             "judul lama tidak boleh dilaporkan lagi")

    async def test_repeat_run_is_quiet(self):
        """Idempoten: judul yang sudah dilapor tidak muncul dua kali."""
        with isolated_db():
            await seeded_db()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload("a"))):
                await scout.poll_thunder_latest()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload("a", "new-one"))):
                first = await scout.poll_thunder_latest()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload("a", "new-one"))):
                second = await scout.poll_thunder_latest()
            self.assertEqual([event["slug"] for event in first], ["new-one"])
            self.assertEqual(second, [], "poll berikutnya harus sunyi")

    async def test_burst_drains_at_the_configured_limit(self):
        """Lebih dari limit diproses bertahap, tidak ada yang hilang."""
        limit = 2
        with isolated_db():
            await seeded_db()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload("seed"))):
                await scout.poll_thunder_latest()
            burst = ["n1", "n2", "n3", "n4", "n5"]
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload(*burst))):
                first = await scout.poll_thunder_latest(limit=limit)
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload(*burst))):
                second = await scout.poll_thunder_latest(limit=limit)
            self.assertEqual([event["slug"] for event in first], ["n1", "n2"])
            self.assertEqual([event["slug"] for event in second], ["n3", "n4"],
                             "sisanya harus menyusul, bukan hilang")
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload(*burst))):
                third = await scout.poll_thunder_latest(limit=limit)
            self.assertEqual([event["slug"] for event in third], ["n5"])

    async def test_failed_api_reports_nothing(self):
        with isolated_db():
            await seeded_db()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value={})):
                self.assertEqual(await scout.poll_thunder_latest(), [])

    async def test_list_marks_seen_titles(self):
        with isolated_db():
            await seeded_db()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload("known"))):
                await scout.poll_thunder_latest()
            with patch.object(scout, "fetch_thunder_latest", AsyncMock(return_value=payload("known", "fresh"))):
                listing = await scout.list_thunder_latest()
            self.assertEqual(listing["order"], "latest")
            self.assertEqual(listing["total"], 2)
            flags = {row["slug"]: row["seen"] for row in listing["data"]}
            self.assertEqual(flags, {"known": True, "fresh": False})

    async def test_isolation_guards_the_production_database(self):
        """Guard: DB_PATH harus berpindah selama tes berjalan."""
        production = database.DB_PATH
        with isolated_db() as path:
            self.assertNotEqual(database.DB_PATH, production)
            self.assertTrue(database.DB_PATH.endswith(".db"))
            self.assertNotIn("data/ryukomik.db", database.DB_PATH)
            self.assertTrue(path.endswith(".db"))
        self.assertEqual(database.DB_PATH, production, "DB_PATH harus dikembalikan")


class LoopWiringTests(unittest.TestCase):
    """Guards against wiring the loop but never starting it."""

    @classmethod
    def setUpClass(cls):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "bot.py"), encoding="utf-8") as handle:
            cls.bot_source = handle.read()

    def test_loop_is_registered_and_started(self):
        self.assertRegex(self.bot_source, r"async def thunder_latest_loop\(")
        self.assertIn("thunder_latest_loop.start()", self.bot_source,
                      "loop didefinisikan tapi tidak pernah .start() = tidak pernah jalan")

    def test_loop_interval_is_half_an_hour(self):
        match = re.search(r"@tasks\.loop\(([^)]*)\)\s*(?:\r?\n)+async def thunder_latest_loop\(", self.bot_source)
        assert match is not None, "dekorator tasks.loop untuk thunder_latest_loop tidak ketemu"
        self.assertEqual(match.group(1).replace(" ", ""), "minutes=30")


if __name__ == "__main__":
    unittest.main()

import unittest
import os
import tempfile
from unittest.mock import AsyncMock, patch

from raw_downloader.omega import OmegaDownloader
from raw_downloader.siren import SirenDownloader
from raw_downloader.resolver import (
    SOURCE_ORDER,
    deduplicate_results,
    resolve_assignment_raw,
)
from views.raw_views import create_filebin_download


class SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return False


class FakeDownloader:
    def __init__(self, results=None, chapters=None):
        self.results = results or []
        self.chapters = chapters or []

    async def search_manga(self, _query):
        return self.results

    async def get_chapter_list(self, _manga_id):
        return self.chapters


class FakePackageDownloader:
    def __init__(self, source, fail=False):
        self.source = source
        self.fail = fail

    async def download_chapter(self, manga_id, chapter_id, save_dir):
        if self.fail:
            return None
        target = os.path.join(save_dir, self.source, f"{manga_id}-{chapter_id}")
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, "001.jpg"), "wb") as image_file:
            image_file.write(b"image")
        return target


def manga(source, title="Shared Title"):
    return {"id": f"{source}-slug", "title": title, "source": source}


def chapters(source, *numbers):
    return [
        {"id": f"chapter-{number}", "title": f"Chapter {number}", "source": source}
        for number in numbers
    ]


class OmegaAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_and_chapter_schema_are_normalized(self):
        downloader = OmegaDownloader()
        search_payload = {
            "data": [{
                "title": "Love Cheer!",
                "slug": "love-cheer",
                "type_genre": "Comic",
                "update": "Chapter 13",
                "image": "cover.webp",
            }]
        }
        with patch("raw_downloader.omega._create_session", return_value=SessionContext()), patch(
            "raw_downloader.omega.get_json", new=AsyncMock(return_value=search_payload)
        ):
            result = await downloader.search_manga("love")
        self.assertEqual(result[0]["id"], "love-cheer")
        self.assertEqual(result[0]["source"], "omega")

        downloader.get_manga_info = AsyncMock(return_value={
            "chapters": [
                {"title": "Chapter 8.5", "slug": "chapter-8.5", "date": "today"},
                {"title": "Chapter 1", "slug": "chapter-1", "date": "yesterday"},
            ]
        })
        chapter_rows = await downloader.get_chapter_list("love-cheer")
        self.assertEqual([row["id"] for row in chapter_rows], ["chapter-8.5", "chapter-1"])

    async def test_image_order_is_preserved(self):
        downloader = OmegaDownloader()
        payload = {"images": ["page-01.jpg", "page-02.jpg", "page-03.jpg"]}
        with patch("raw_downloader.omega._create_session", return_value=SessionContext()), patch(
            "raw_downloader.omega.get_json", new=AsyncMock(return_value=payload)
        ):
            images = await downloader.get_chapter_images("love-cheer", "1")
        self.assertEqual(images, payload["images"])


class SirenAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_and_chapter_schema_are_normalized(self):
        downloader = SirenDownloader()
        search_payload = {"data": [{
            "title": "The Girl Next to Me Is a Beast", "slug": "64db57fa096",
            "type_genre": "manga", "image": "cover.webp",
        }]}
        with patch("raw_downloader.siren._create_session", return_value=SessionContext()), patch(
            "raw_downloader.siren.get_json", new=AsyncMock(return_value=search_payload)
        ):
            result = await downloader.search_manga("girl beast")
        self.assertEqual(result[0]["id"], "64db57fa096")
        self.assertEqual(result[0]["source"], "siren")

        downloader.get_manga_info = AsyncMock(return_value={"chapters": [{
            "title": "Chapter 4", "slug": "chapter-4", "date": "today",
        }]})
        chapter_rows = await downloader.get_chapter_list("64db57fa096")
        self.assertEqual(chapter_rows[0]["id"], "chapter-4")

    async def test_image_order_is_preserved(self):
        downloader = SirenDownloader()
        payload = {"images": ["page-01.jpg", "page-02.jpg", "page-03.jpg"]}
        with patch("raw_downloader.siren._create_session", return_value=SessionContext()), patch(
            "raw_downloader.siren.get_json", new=AsyncMock(return_value=payload)
        ):
            images = await downloader.get_chapter_images("64db57fa096", "4")
        self.assertEqual(images, payload["images"])


class ThreeSourceResolverTests(unittest.IsolatedAsyncioTestCase):
    def test_duplicate_titles_are_grouped_with_all_candidates(self):
        grouped = deduplicate_results({
            "asura": [],
            "omega": [manga("omega")],
            "doujiva": [manga("doujiva")],
        })
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["_source"], "omega")
        self.assertEqual(set(grouped[0]["_sources"]), {"omega", "doujiva"})

    async def test_more_complete_omega_beats_asura_and_doujiva(self):
        downloaders = {
            "asura": FakeDownloader([manga("asura")], chapters("asura", 1)),
            "omega": FakeDownloader([manga("omega")], chapters("omega", 1, 2, 3)),
            "doujiva": FakeDownloader([manga("doujiva")], chapters("doujiva", 1, 2)),
        }
        result = await resolve_assignment_raw("Shared Title", ["1", "2", "3"], downloaders)
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["source"], "omega")
        self.assertEqual(result["missing"], [])

    async def test_equal_coverage_uses_business_priority(self):
        self.assertEqual(SOURCE_ORDER, ("asura", "omega", "doujiva", "siren"))
        downloaders = {
            source: FakeDownloader([manga(source)], chapters(source, 1, 2))
            for source in SOURCE_ORDER
        }
        result = await resolve_assignment_raw("Shared Title", ["1", "2"], downloaders)
        self.assertEqual(result["source"], "asura")
        self.assertEqual(
            [item["source"] for item in result["fallbacks"]],
            ["omega", "doujiva", "siren"],
        )

    async def test_partial_sources_are_not_merged(self):
        downloaders = {
            "asura": FakeDownloader([], []),
            "omega": FakeDownloader([manga("omega")], chapters("omega", 1, 2)),
            "doujiva": FakeDownloader([manga("doujiva")], chapters("doujiva", 3)),
        }
        result = await resolve_assignment_raw("Shared Title", ["1", "2", "3"], downloaders)
        self.assertEqual(result["source"], "omega")
        self.assertEqual(
            [row["id"] for row in result["chapters"]],
            ["chapter-1", "chapter-2"],
        )
        self.assertEqual(result["missing"], ["3"])
        self.assertEqual(result["fallbacks"], [])

    async def test_failed_source_falls_back_as_one_complete_package(self):
        downloaders = {
            "omega": FakePackageDownloader("omega", fail=True),
            "doujiva": FakePackageDownloader("doujiva"),
        }
        with tempfile.TemporaryDirectory() as temporary, patch(
            "views.raw_views.RAW_ROOT", temporary
        ), patch(
            "views.raw_views.get_downloader",
            side_effect=lambda source: downloaders[source],
        ), patch(
            "views.raw_views.upload_to_filebin",
            new=AsyncMock(return_value=True),
        ):
            url, completed, final_source = await create_filebin_download(
                "omega",
                "shared-title",
                ["1", "2"],
                [{"source": "doujiva", "manga_id": "shared-title"}],
            )
        self.assertTrue(url.startswith("https://filebin.net/"))
        self.assertEqual(completed, ["1", "2"])
        self.assertEqual(final_source, "doujiva")

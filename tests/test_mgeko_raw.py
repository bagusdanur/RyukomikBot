import unittest
from unittest.mock import AsyncMock, patch

from raw_downloader import get_downloader
from raw_downloader.mgeko import MgekoDownloader


class SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class MgekoDownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_normalizes_result(self):
        payload = {
            "success": True,
            "data": [
                {
                    "title": "Mgeko Manga",
                    "slug": "mgeko-manga",
                    "image": "https://api.ryukomik.web.id/mgeko/image?url=https%3A%2F%2Fmgeko.cc%2Fcover.jpg",
                    "type_genre": "manga",
                    "update": "Chapter 25",
                    "rating": "8.7",
                }
            ],
        }
        with patch("raw_downloader.mgeko._session", return_value=SessionContext()), patch(
            "raw_downloader.mgeko.get_json", new=AsyncMock(return_value=payload)
        ):
            result = await MgekoDownloader().search_manga("Mgeko")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "mgeko-manga")
        self.assertEqual(result[0]["title"], "Mgeko Manga")
        self.assertEqual(result[0]["source"], "mgeko")

    async def test_chapter_list_keeps_api_slug_and_locked_flag(self):
        downloader = MgekoDownloader()
        downloader.get_manga_info = AsyncMock(
            return_value={
                "chapters": [
                    {
                        "title": "Chapter 25",
                        "slug": "chapter-25-eng-li",
                        "date": "1 day ago",
                        "locked": False,
                    },
                    {
                        "title": "Chapter 24",
                        "slug": "chapter-24-eng-li",
                        "date": "5 days ago",
                        "locked": True,
                    },
                ]
            }
        )
        chapters = await downloader.get_chapter_list("mgeko-manga")
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0]["id"], "chapter-25-eng-li")
        self.assertEqual(chapters[0]["title"], "Chapter 25")
        self.assertFalse(chapters[0]["locked"])
        self.assertEqual(chapters[1]["id"], "chapter-24-eng-li")
        self.assertTrue(chapters[1]["locked"])

    async def test_numeric_chapter_resolves_to_official_slug(self):
        downloader = MgekoDownloader()
        downloader.get_chapter_list = AsyncMock(
            return_value=[
                {
                    "id": "chapter-25-eng-li",
                    "title": "Chapter 25",
                }
            ]
        )
        get_json = AsyncMock(return_value={"images": ["page-1.webp", "page-2.webp"]})
        with patch("raw_downloader.mgeko._session", return_value=SessionContext()), patch(
            "raw_downloader.mgeko.get_json", new=get_json
        ):
            images = await downloader.get_chapter_images("mgeko-manga", "25")
        self.assertEqual(images, ["page-1.webp", "page-2.webp"])
        self.assertIn("/chapter-25-eng-li", get_json.await_args.args[1])

    def test_get_downloader_accepts_aliases(self):
        self.assertIsInstance(get_downloader("mgeko"), MgekoDownloader)
        self.assertIsInstance(get_downloader("mgekocc"), MgekoDownloader)
        self.assertIsInstance(get_downloader("mgeko.cc"), MgekoDownloader)
        self.assertIsInstance(get_downloader("geko"), MgekoDownloader)


if __name__ == "__main__":
    unittest.main()

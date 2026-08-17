import unittest
from unittest.mock import AsyncMock, patch

from raw_downloader import get_downloader
from raw_downloader.vortex import VortexDownloader


class SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class VortexDownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_normalizes_result(self):
        payload = {
            "success": True,
            "data": [
                {
                    "title": "Vortex Comic",
                    "slug": "vortex-comic",
                    "image": "https://api.ryukomik.web.id/vortex/image?url=https%3A%2F%2Fstorage.vortexscans.org%2Fcover.jpg",
                    "type_genre": "manhwa",
                    "update": "Chapter 10",
                    "rating": "8.5",
                }
            ],
        }
        with patch("raw_downloader.vortex._session", return_value=SessionContext()), patch(
            "raw_downloader.vortex.get_json", new=AsyncMock(return_value=payload)
        ):
            result = await VortexDownloader().search_manga("Vortex")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "vortex-comic")
        self.assertEqual(result[0]["title"], "Vortex Comic")
        self.assertEqual(result[0]["source"], "vortex")

    async def test_chapter_list_keeps_api_slug_and_locked_flag(self):
        downloader = VortexDownloader()
        downloader.get_manga_info = AsyncMock(
            return_value={
                "chapters": [
                    {
                        "title": "Chapter 35",
                        "slug": "chapter-35",
                        "date": "4 days",
                        "locked": True,
                    },
                    {
                        "title": "Chapter 34",
                        "slug": "chapter-34",
                        "date": "4 days",
                        "locked": False,
                    },
                ]
            }
        )
        chapters = await downloader.get_chapter_list("vortex-comic")
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0]["id"], "chapter-35")
        self.assertEqual(chapters[0]["title"], "Chapter 35")
        self.assertTrue(chapters[0]["locked"])
        self.assertEqual(chapters[1]["id"], "chapter-34")
        self.assertFalse(chapters[1]["locked"])

    async def test_numeric_chapter_resolves_to_official_slug(self):
        downloader = VortexDownloader()
        downloader.get_chapter_list = AsyncMock(
            return_value=[
                {
                    "id": "chapter-34",
                    "title": "Chapter 34",
                }
            ]
        )
        get_json = AsyncMock(return_value={"images": ["page-1.webp", "page-2.webp"]})
        with patch("raw_downloader.vortex._session", return_value=SessionContext()), patch(
            "raw_downloader.vortex.get_json", new=get_json
        ):
            images = await downloader.get_chapter_images("the-regressed-sword-saint", "34")
        self.assertEqual(images, ["page-1.webp", "page-2.webp"])
        self.assertIn("/chapter-34", get_json.await_args.args[1])

    def test_get_downloader_accepts_aliases(self):
        self.assertIsInstance(get_downloader("vortex"), VortexDownloader)
        self.assertIsInstance(get_downloader("vortexscan"), VortexDownloader)
        self.assertIsInstance(get_downloader("vortexscans"), VortexDownloader)


if __name__ == "__main__":
    unittest.main()

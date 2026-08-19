import unittest
from unittest.mock import AsyncMock, patch

from raw_downloader import get_downloader
from raw_downloader.kagane import KaganeDownloader


class SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class KaganeDownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_normalizes_result(self):
        payload = {
            "success": True,
            "data": [
                {
                    "title": "Kagane Comic",
                    "slug": "kagane-comic",
                    "image": "https://api.ryukomik.web.id/kagane/image?url=https%3A%2F%2Fkagane.to%2Fcover.jpg",
                    "type_genre": "manhwa",
                    "update": "Chapter 12",
                    "rating": "9.0",
                }
            ],
        }
        with patch("raw_downloader.kagane._session", return_value=SessionContext()), patch(
            "raw_downloader.kagane.get_json", new=AsyncMock(return_value=payload)
        ):
            result = await KaganeDownloader().search_manga("Kagane")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "kagane-comic")
        self.assertEqual(result[0]["title"], "Kagane Comic")
        self.assertEqual(result[0]["source"], "kagane")

    async def test_chapter_list_keeps_api_slug_and_locked_flag(self):
        downloader = KaganeDownloader()
        downloader.get_manga_info = AsyncMock(
            return_value={
                "chapters": [
                    {
                        "title": "Chapter 12",
                        "slug": "chapter-12",
                        "date": "2 days ago",
                        "locked": True,
                    },
                    {
                        "title": "Chapter 11",
                        "slug": "chapter-11",
                        "date": "3 days ago",
                        "locked": False,
                    },
                ]
            }
        )
        chapters = await downloader.get_chapter_list("kagane-comic")
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0]["id"], "chapter-12")
        self.assertEqual(chapters[0]["title"], "Chapter 12")
        self.assertTrue(chapters[0]["locked"])
        self.assertEqual(chapters[1]["id"], "chapter-11")
        self.assertFalse(chapters[1]["locked"])

    async def test_numeric_chapter_resolves_to_official_slug(self):
        downloader = KaganeDownloader()
        downloader.get_chapter_list = AsyncMock(
            return_value=[
                {
                    "id": "chapter-12",
                    "title": "Chapter 12",
                }
            ]
        )
        get_json = AsyncMock(return_value={"images": ["page-1.webp", "page-2.webp"]})
        with patch("raw_downloader.kagane._session", return_value=SessionContext()), patch(
            "raw_downloader.kagane.get_json", new=get_json
        ):
            images = await downloader.get_chapter_images("kagane-comic", "12")
        self.assertEqual(images, ["page-1.webp", "page-2.webp"])
        self.assertIn("/chapter-12", get_json.await_args.args[1])

    def test_get_downloader_accepts_aliases(self):
        self.assertIsInstance(get_downloader("kagane"), KaganeDownloader)
        self.assertIsInstance(get_downloader("kaganeto"), KaganeDownloader)
        self.assertIsInstance(get_downloader("kagane.to"), KaganeDownloader)


if __name__ == "__main__":
    unittest.main()

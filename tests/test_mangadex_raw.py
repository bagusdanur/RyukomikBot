import unittest
from unittest.mock import AsyncMock, patch

from raw_downloader import get_downloader
from raw_downloader.mangadex import MangaDexDownloader


class SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return None


class MangaDexDownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_maps_title_cover_and_id(self):
        payload = {"data": [{
            "id": "manga-id",
            "attributes": {"title": {"en": "Please Let Me Be Proud"}, "status": "ongoing"},
            "relationships": [{"type": "cover_art", "attributes": {"fileName": "cover.jpg"}}],
        }]}
        with patch("raw_downloader.mangadex._session", return_value=SessionContext()), patch(
            "raw_downloader.mangadex.get_json", new=AsyncMock(return_value=payload)
        ):
            [result] = await MangaDexDownloader().search_manga("Please Let Me Be Proud")
        self.assertEqual(result["id"], "manga-id")
        self.assertEqual(result["title"], "Please Let Me Be Proud")
        self.assertEqual(result["source"], "mangadex")
        self.assertIn("cover.jpg.256.jpg", result["image"])

    async def test_at_home_images_keep_api_order(self):
        payload = {"baseUrl": "https://uploads.example", "chapter": {"hash": "hash", "data": ["1.jpg", "2.png"]}}
        with patch("raw_downloader.mangadex._session", return_value=SessionContext()), patch(
            "raw_downloader.mangadex.get_json", new=AsyncMock(return_value=payload)
        ):
            images = await MangaDexDownloader().get_chapter_images("manga-id", "chapter-id")
        self.assertEqual(images, [
            "https://uploads.example/data/hash/1.jpg",
            "https://uploads.example/data/hash/2.png",
        ])

    def test_registry_aliases(self):
        self.assertIsInstance(get_downloader("mangadex"), MangaDexDownloader)
        self.assertIsInstance(get_downloader("mdex"), MangaDexDownloader)


if __name__ == "__main__":
    unittest.main()

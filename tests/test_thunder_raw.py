import unittest
from unittest.mock import AsyncMock, patch

from raw_downloader import get_downloader
from raw_downloader.thunder import ThunderDownloader


class SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class ThunderDownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_normalizes_result(self):
        payload = {"data": [{"title": "Thunder Manga", "slug": "thunder-manga", "image": "cover.jpg", "type_genre": "comic"}]}
        with patch("raw_downloader.thunder._create_session", return_value=SessionContext()), patch(
            "raw_downloader.thunder.get_json", new=AsyncMock(return_value=payload)
        ):
            result = await ThunderDownloader().search_manga("Thunder")
        self.assertEqual(result[0]["id"], "thunder-manga")
        self.assertEqual(result[0]["source"], "thunder")

    async def test_chapter_list_keeps_api_slug(self):
        downloader = ThunderDownloader()
        downloader.get_manga_info = AsyncMock(return_value={"chapters": [{"title": "Chapter 27.2", "slug": "thunder-manga-chapter-27-2", "date": "Today"}]})
        chapters = await downloader.get_chapter_list("thunder-manga")
        self.assertEqual(chapters[0]["id"], "thunder-manga-chapter-27-2")
        self.assertEqual(chapters[0]["title"], "Chapter 27.2")

    async def test_images_preserve_top_to_bottom_order(self):
        payload = {"success": True, "images": ["page-1.jpg", "page-2.jpg", "page-3.jpg"]}
        with patch("raw_downloader.thunder._create_session", return_value=SessionContext()), patch(
            "raw_downloader.thunder.get_json", new=AsyncMock(return_value=payload)
        ):
            images = await ThunderDownloader().get_chapter_images("thunder-manga", "thunder-manga-chapter-1")
        self.assertEqual(images, ["page-1.jpg", "page-2.jpg", "page-3.jpg"])

    def test_get_downloader_accepts_aliases(self):
        self.assertIsInstance(get_downloader("thunder"), ThunderDownloader)
        self.assertIsInstance(get_downloader("thunderscans"), ThunderDownloader)


if __name__ == "__main__":
    unittest.main()

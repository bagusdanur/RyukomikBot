import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from raw_downloader.evascan import EvaScanDownloader, canonical_chapter_slug


class EvaScanRawTests(unittest.IsolatedAsyncioTestCase):
    def test_numeric_chapter_becomes_official_evascan_slug(self):
        self.assertEqual(
            canonical_chapter_slug("hush-now-saintess", "2"),
            "hush-now-saintess-chapter-2",
        )
        self.assertEqual(
            canonical_chapter_slug("hush-now-saintess", "hush-now-saintess-chapter-2"),
            "hush-now-saintess-chapter-2",
        )

    async def test_chapter_download_reuses_one_session_and_reports_progress(self):
        downloader = EvaScanDownloader()
        images = [f"https://example.invalid/{index}.webp" for index in range(1, 6)]
        progress = AsyncMock()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            downloader, "get_chapter_images", AsyncMock(return_value=images)
        ), patch("raw_downloader.evascan.download_images", new=AsyncMock(return_value=True)) as download:
            result = await downloader.download_chapter("manga", "chapter-2", directory, progress=progress)
        self.assertIsNotNone(result)
        download.assert_awaited_once()
        self.assertEqual(download.await_args.kwargs["timeout"], 20)
        self.assertEqual(download.await_args.kwargs["concurrency"], 4)


if __name__ == "__main__":
    unittest.main()

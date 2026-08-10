import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from raw_downloader.evascan import EvaScanDownloader


class EvaScanRawTests(unittest.IsolatedAsyncioTestCase):
    async def test_chapter_download_reuses_one_session_and_reports_progress(self):
        downloader = EvaScanDownloader()
        images = [f"https://example.invalid/{index}.webp" for index in range(1, 6)]
        progress = AsyncMock()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            downloader, "get_chapter_images", AsyncMock(return_value=images)
        ), patch.object(downloader, "download_image", AsyncMock(return_value=True)) as download:
            result = await downloader.download_chapter("manga", "chapter-2", directory, progress=progress)
        self.assertIsNotNone(result)
        self.assertEqual(download.await_count, 5)
        reported = [call.args for call in progress.await_args_list]
        self.assertIn((4, 5), reported)
        self.assertIn((5, 5), reported)


if __name__ == "__main__":
    unittest.main()

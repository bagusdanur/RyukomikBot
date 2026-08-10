import tempfile
import unittest
from unittest.mock import patch

from raw_downloader.retry import download_images


class RawRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_download_keeps_numbered_page_order(self):
        session = object()

        async def fake_get_bytes(_session, url, **_kwargs):
            return url.encode()

        with tempfile.TemporaryDirectory() as directory:
            with patch("raw_downloader.retry.get_bytes", side_effect=fake_get_bytes):
                complete = await download_images(
                    session,
                    ["https://raw/first.webp", "https://raw/second.webp"],
                    directory,
                    source="test",
                    extension_for=lambda _url: "webp",
                )
            self.assertTrue(complete)
            with open(f"{directory}/001.webp", "rb") as image:
                self.assertEqual(image.read(), b"https://raw/first.webp")
            with open(f"{directory}/002.webp", "rb") as image:
                self.assertEqual(image.read(), b"https://raw/second.webp")

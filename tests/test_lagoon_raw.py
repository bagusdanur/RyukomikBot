import unittest
from unittest.mock import AsyncMock, patch

from raw_downloader import get_downloader
from raw_downloader.lagoon import LagoonDownloader


class SessionContext:
    async def __aenter__(self): return object()
    async def __aexit__(self, *args): return None


class LagoonDownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_uses_lagoon_source(self):
        payload = {"data": [{"title": "Solo Max-Level Newbie", "slug": "solo-max-level-newbie"}]}
        with patch("raw_downloader.dusk._session", return_value=SessionContext()), patch(
            "raw_downloader.dusk.get_json", new=AsyncMock(return_value=payload)
        ):
            [result] = await LagoonDownloader().search_manga("solo")
        self.assertEqual(result["source"], "lagoon")
        self.assertEqual(result["id"], "solo-max-level-newbie")

    def test_registry(self):
        self.assertIsInstance(get_downloader("lagoon"), LagoonDownloader)
        self.assertIsInstance(get_downloader("lagoonscans"), LagoonDownloader)


if __name__ == "__main__": unittest.main()

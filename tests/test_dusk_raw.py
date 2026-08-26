import unittest

from raw_downloader import get_downloader
from raw_downloader.dusk import DuskDownloader


class DuskDownloaderTests(unittest.TestCase):
    def test_registry_aliases(self):
        self.assertIsInstance(get_downloader("dusk"), DuskDownloader)
        self.assertIsInstance(get_downloader("duskscans"), DuskDownloader)


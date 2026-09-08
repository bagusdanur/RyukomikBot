import unittest
from raw_downloader import get_downloader
from raw_downloader.ken import KenDownloader


class KenDownloaderTests(unittest.TestCase):
    def test_registry(self):
        self.assertIsInstance(get_downloader("ken"), KenDownloader)
        self.assertIsInstance(get_downloader("kencomics"), KenDownloader)


if __name__ == "__main__": unittest.main()

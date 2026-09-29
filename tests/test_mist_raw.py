import unittest
from unittest.mock import AsyncMock, patch

from raw_downloader import get_downloader, mist_downloader, search_mist
from raw_downloader.dusk import DuskDownloader
from raw_downloader.mist import MistDownloader


class MistDownloaderTests(unittest.TestCase):
    def test_registry_aliases(self):
        for alias in ("mist", "MIST", "mistscan", "mistscans", "mistscans.com"):
            with self.subTest(alias=alias):
                self.assertIsInstance(get_downloader(alias), MistDownloader)

    def test_uses_mist_api_and_source(self):
        self.assertEqual(mist_downloader.source, "mist")
        self.assertTrue(mist_downloader.api_url.endswith("/mist"),
                        f"API tidak mengarah ke /mist: {mist_downloader.api_url}")

    def test_inherits_dusk_flow(self):
        # Mist memakai kontrak API yang sama dengan Dusk/Lua; jangan
        # menggandakan logika kalau hanya perlu satu override.
        self.assertIsInstance(mist_downloader, DuskDownloader)

    def test_search_helper_terpasang(self):
        self.assertTrue(callable(search_mist))


class MistChapterSlugTests(unittest.IsolatedAsyncioTestCase):
    """Mist menomori chapter di judul tapi mengalamatkannya lewat hash.

    `64f6dd0cdf8-65bb0190b9c` tidak memuat angka, jadi logika resolusi
    numerik milik DuskDownloader menggantinya dengan chapter pertama dan
    mengunduh halaman yang salah. Override harus meneruskan slug apa adanya.
    """

    async def _capture(self, chapter_id):
        """Kembalikan chapter_id yang benar-benar diterima lapisan induk."""
        spy = AsyncMock(return_value=[])
        with patch.object(DuskDownloader, "get_chapter_images", spy):
            await mist_downloader.get_chapter_images("solo-ex-rank-summoner", chapter_id)
        if not spy.await_count:
            return None
        return spy.await_args.args[1]

    async def test_slug_hash_diteruskan_apa_adanya(self):
        slug = "64f6dd0cdf8-65bb0190b9c"
        self.assertEqual(await self._capture(slug), slug,
                         "slug hash tidak boleh diubah")

    async def test_slug_dibersihkan_dari_slash(self):
        slug = "64f6dd0cdf8-65bb0190b9c"
        self.assertEqual(await self._capture(f"/{slug}/"), slug)

    async def test_slug_kosong_tidak_memanggil_induk(self):
        for value in ("", "   ", "/", None):
            with self.subTest(value=value):
                spy = AsyncMock(return_value=[])
                with patch.object(DuskDownloader, "get_chapter_images", spy):
                    result = await mist_downloader.get_chapter_images("solo", value)
                self.assertEqual(result, [])
                self.assertEqual(spy.await_count, 0,
                                 "slug kosong tidak boleh menembak API")

    async def test_nomor_polos_tetap_diteruskan(self):
        # API Mist juga menerima nomor karena judul chapter memuat angkanya
        self.assertEqual(await self._capture("40"), "40")


if __name__ == "__main__":
    unittest.main()

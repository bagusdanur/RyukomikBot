from pathlib import Path

from config import MGREAD_API
from .dusk import DuskDownloader


class MgreadDownloader(DuskDownloader):
    """Downloader for the Ryukomik MGRead API."""

    def __init__(self):
        super().__init__(MGREAD_API, "mgread")

    @staticmethod
    def _remove_opening_promo(path: Path) -> None:
        """Keep the source page byte-for-byte intact.

        Promo removal based only on a visual boundary repeatedly mistook dark
        opening panels for banners. Branding cleanup may mask a confirmed promo,
        but the downloader must never crop artwork or alter page dimensions.
        """
        del path

    async def download_chapter(self, manga_id: str, chapter_id: str, save_dir: str):
        folder = await super().download_chapter(manga_id, chapter_id, save_dir)
        if folder:
            first = next(iter(sorted(Path(folder).glob("001.*"))), None)
            if first:
                self._remove_opening_promo(first)
        return folder


mgread_downloader = MgreadDownloader()


async def search_mgread(query: str):
    return await mgread_downloader.search_manga(query)

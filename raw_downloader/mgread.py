from config import MGREAD_API
from .dusk import DuskDownloader


class MgreadDownloader(DuskDownloader):
    """Downloader for the Ryukomik MGRead API."""

    def __init__(self):
        super().__init__(MGREAD_API, "mgread")


mgread_downloader = MgreadDownloader()


async def search_mgread(query: str):
    return await mgread_downloader.search_manga(query)

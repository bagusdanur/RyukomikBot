from config import KEN_API
from .dusk import DuskDownloader


class KenDownloader(DuskDownloader):
    """Downloader for the Ryukomik Ken Comics API."""

    def __init__(self):
        super().__init__(KEN_API, "ken")


ken_downloader = KenDownloader()


async def search_ken(query: str):
    return await ken_downloader.search_manga(query)

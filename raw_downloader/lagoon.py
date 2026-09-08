from config import LAGOON_API
from .dusk import DuskDownloader


class LagoonDownloader(DuskDownloader):
    """Downloader for the Ryukomik Lagoon Scans API."""

    def __init__(self):
        super().__init__(LAGOON_API, "lagoon")


lagoon_downloader = LagoonDownloader()


async def search_lagoon(query: str):
    return await lagoon_downloader.search_manga(query)

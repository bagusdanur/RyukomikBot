from .asura import AsuraDownloader, search_asura
from .doujiva import DoujivaDownloader, search_doujiva

asura_downloader = AsuraDownloader()
doujiva_downloader = DoujivaDownloader()


def get_downloader(source: str = "asura"):
    """Get downloader instance based on source name."""
    if source.casefold() in ("doujiva", "doujin"):
        return doujiva_downloader
    return asura_downloader


__all__ = [
    "AsuraDownloader",
    "DoujivaDownloader",
    "search_asura",
    "search_doujiva",
    "get_downloader",
    "asura_downloader",
    "doujiva_downloader",
]

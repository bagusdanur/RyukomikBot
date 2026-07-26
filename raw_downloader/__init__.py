from .asura import AsuraDownloader, search_asura
from .doujiva import DoujivaDownloader, search_doujiva
from .omega import OmegaDownloader, search_omega

asura_downloader = AsuraDownloader()
doujiva_downloader = DoujivaDownloader()
omega_downloader = OmegaDownloader()


def get_downloader(source: str = "asura"):
    """Get downloader instance based on source name."""
    if source.casefold() in ("doujiva", "doujin"):
        return doujiva_downloader
    if source.casefold() == "omega":
        return omega_downloader
    if source.casefold() == "asura":
        return asura_downloader
    raise ValueError(f"Sumber RAW tidak dikenal: {source}")


__all__ = [
    "AsuraDownloader",
    "DoujivaDownloader",
    "OmegaDownloader",
    "search_asura",
    "search_doujiva",
    "search_omega",
    "get_downloader",
    "asura_downloader",
    "doujiva_downloader",
    "omega_downloader",
]

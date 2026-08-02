from .asura import AsuraDownloader, search_asura
from .doujiva import DoujivaDownloader, search_doujiva
from .omega import OmegaDownloader, search_omega
from .siren import SirenDownloader, search_siren

asura_downloader = AsuraDownloader()
doujiva_downloader = DoujivaDownloader()
omega_downloader = OmegaDownloader()
siren_downloader = SirenDownloader()


def get_downloader(source: str = "asura"):
    """Get downloader instance based on source name."""
    if source.casefold() in ("doujiva", "doujin"):
        return doujiva_downloader
    if source.casefold() == "omega":
        return omega_downloader
    if source.casefold() == "siren":
        return siren_downloader
    if source.casefold() == "asura":
        return asura_downloader
    raise ValueError(f"Sumber RAW tidak dikenal: {source}")


__all__ = [
    "AsuraDownloader",
    "DoujivaDownloader",
    "OmegaDownloader",
    "SirenDownloader",
    "search_asura",
    "search_doujiva",
    "search_omega",
    "search_siren",
    "get_downloader",
    "asura_downloader",
    "doujiva_downloader",
    "omega_downloader",
    "siren_downloader",
]

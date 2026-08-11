from .asura import AsuraDownloader, search_asura
from .doujiva import DoujivaDownloader, search_doujiva
from .omega import OmegaDownloader, search_omega
from .evascan import EvaScanDownloader, search_evascan
from .thunder import ThunderDownloader, search_thunder
from .qimanga import QiMangaDownloader
from .demon import DemonDownloader

asura_downloader = AsuraDownloader()
doujiva_downloader = DoujivaDownloader()
omega_downloader = OmegaDownloader()
evascan_downloader = EvaScanDownloader()
thunder_downloader = ThunderDownloader()
qimanga_downloader = QiMangaDownloader()
demon_downloader = DemonDownloader()


def get_downloader(source: str = "asura"):
    """Get downloader instance based on source name."""
    if source.casefold() in ("doujiva", "doujin"):
        return doujiva_downloader
    if source.casefold() == "omega":
        return omega_downloader
    if source.casefold() in ("evascan", "eva"):
        return evascan_downloader
    if source.casefold() in ("thunder", "thunderscan", "thunderscans"):
        return thunder_downloader
    if source.casefold() in ("qimanga", "qi"):
        return qimanga_downloader
    if source.casefold() in ("demon", "demonicscans"):
        return demon_downloader
    if source.casefold() == "asura":
        return asura_downloader
    raise ValueError(f"Sumber RAW tidak dikenal: {source}")


__all__ = [
    "AsuraDownloader",
    "DoujivaDownloader",
    "OmegaDownloader",
    "EvaScanDownloader",
    "ThunderDownloader",
    "search_asura",
    "search_doujiva",
    "search_omega",
    "search_evascan",
    "search_thunder",
    "get_downloader",
    "asura_downloader",
    "doujiva_downloader",
    "omega_downloader",
    "evascan_downloader",
    "thunder_downloader",
]

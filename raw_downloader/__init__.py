from .asura import AsuraDownloader, search_asura
from .doujiva import DoujivaDownloader, search_doujiva
from .omega import OmegaDownloader, search_omega
from .evascan import EvaScanDownloader, search_evascan
from .thunder import ThunderDownloader, search_thunder
from .qimanga import QiMangaDownloader
from .demon import DemonDownloader
from .vortex import VortexDownloader, search_vortex
from .kagane import KaganeDownloader, search_kagane
from .mgeko import MgekoDownloader, search_mgeko
from .dusk import DuskDownloader, search_dusk
from config import DIVA_API

asura_downloader = AsuraDownloader()
doujiva_downloader = DoujivaDownloader()
diva_downloader = DoujivaDownloader(DIVA_API, "diva")
omega_downloader = OmegaDownloader()
evascan_downloader = EvaScanDownloader()
thunder_downloader = ThunderDownloader()
qimanga_downloader = QiMangaDownloader()
demon_downloader = DemonDownloader()
vortex_downloader = VortexDownloader()
kagane_downloader = KaganeDownloader()
mgeko_downloader = MgekoDownloader()
dusk_downloader = DuskDownloader()


def get_downloader(source: str = "asura"):
    """Get downloader instance based on source name."""
    if source.casefold() in ("doujiva", "doujin"):
        return doujiva_downloader
    if source.casefold() in ("diva", "divascans"):
        return diva_downloader
    if source.casefold() == "omega":
        return omega_downloader
    if source.casefold() in ("evascan", "eva"):
        return evascan_downloader
    if source.casefold() in ("thunder", "thunderscan", "thunderscans"):
        return thunder_downloader
    if source.casefold() in ("vortex", "vortexscan", "vortexscans"):
        return vortex_downloader
    if source.casefold() in ("qimanga", "qi"):
        return qimanga_downloader
    if source.casefold() in ("demon", "demonicscans"):
        return demon_downloader
    if source.casefold() in ("kagane", "kaganeto", "kagane.to"):
        return kagane_downloader
    if source.casefold() in ("mgeko", "mgekocc", "mgeko.cc", "geko"):
        return mgeko_downloader
    if source.casefold() in ("dusk", "duskscans"):
        return dusk_downloader
    if source.casefold() == "asura":
        return asura_downloader
    raise ValueError(f"Sumber RAW tidak dikenal: {source}")


__all__ = [
    "AsuraDownloader",
    "DoujivaDownloader",
    "OmegaDownloader",
    "EvaScanDownloader",
    "ThunderDownloader",
    "VortexDownloader",
    "QiMangaDownloader",
    "DemonDownloader",
    "KaganeDownloader",
    "MgekoDownloader",
    "DuskDownloader",
    "search_asura",
    "search_doujiva",
    "search_omega",
    "search_evascan",
    "search_thunder",
    "search_vortex",
    "search_kagane",
    "search_mgeko",
    "search_dusk",
    "get_downloader",
    "asura_downloader",
    "doujiva_downloader",
    "diva_downloader",
    "omega_downloader",
    "evascan_downloader",
    "thunder_downloader",
    "vortex_downloader",
    "qimanga_downloader",
    "demon_downloader",
    "kagane_downloader",
    "mgeko_downloader",
    "dusk_downloader",
]

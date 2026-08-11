import os, shutil
from urllib.parse import parse_qs, unquote, urlparse
import aiohttp
from config import QIMANGA_API
from .retry import download_images, get_json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
def _session(): return aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver()), headers=HEADERS)
def _id(v): return str(v or "").strip("/").removeprefix("series/").removeprefix("manga/")
def _chapter(v):
    v = str(v or "").strip("/").split("/")[-1]
    return f"chapter-{v}" if v.replace(".", "", 1).isdigit() else v
def _ext(url):
    url = unquote((parse_qs(urlparse(url).query).get("url") or [url])[0])
    suffix = os.path.splitext(urlparse(url).path)[1].lower()
    return suffix.lstrip(".") if suffix in {".jpg", ".jpeg", ".png", ".webp"} else "jpg"

class QiMangaDownloader:
    def __init__(self): self.api_url = QIMANGA_API.rstrip("/")
    async def search_manga(self, query):
        async with _session() as s: data = await get_json(s, f"{self.api_url}/search", source="qimanga", stage="search", params={"q": query}, timeout=4, validator=lambda p: isinstance(p.get("data"), list))
        return [{"id": _id(x.get("slug")), "title": x.get("title", "Unknown"), "status": x.get("type_genre", "N/A"), "chapter_count": x.get("update", "N/A"), "image": x.get("image", ""), "source": "qimanga"} for x in (data or {}).get("data", []) if x.get("slug")]
    async def get_manga_info(self, manga_id):
        manga_id = _id(manga_id)
        async with _session() as s: data = await get_json(s, f"{self.api_url}/detail/{manga_id}", source="qimanga", stage=f"detail:{manga_id}", timeout=5, validator=lambda p: bool((p.get("data") or {}).get("chapters")))
        return data.get("data") if data else None
    async def get_chapter_list(self, manga_id):
        info, manga_id = await self.get_manga_info(manga_id), _id(manga_id)
        return [{"id": _chapter(x.get("slug", x.get("title"))), "title": x.get("title", "Unknown Chapter"), "date": x.get("date", x.get("time", "")), "manga_id": manga_id, "source": "qimanga"} for x in (info or {}).get("chapters", []) if x.get("slug") or x.get("title")]
    async def get_chapter_images(self, manga_id, chapter_id):
        manga_id, chapter_id = _id(manga_id), _chapter(chapter_id)
        async with _session() as s: data = await get_json(s, f"{self.api_url}/chapter/{manga_id}/{chapter_id}", source="qimanga", stage=f"chapter:{manga_id}:{chapter_id}", timeout=10, validator=lambda p: bool(p.get("images")))
        return [str(x).strip() for x in (data or {}).get("images", []) if str(x).strip()]
    async def download_chapter(self, manga_id, chapter_id, save_dir):
        images = await self.get_chapter_images(manga_id, chapter_id)
        if not images: return None
        target = os.path.join(save_dir, "qimanga", f"{_id(manga_id)}_{_chapter(chapter_id)}")
        async with _session() as s: ok = await download_images(s, images, target, source="qimanga", extension_for=_ext, concurrency=4, timeout=20)
        if ok: return target
        shutil.rmtree(target, ignore_errors=True); return None

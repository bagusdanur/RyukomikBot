import os
import re
import shutil
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp

from config import DUSK_API
from .retry import download_images, get_json

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def _session():
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver()), headers=HEADERS)


def _id(value: str) -> str:
    return str(value or "").strip("/").removeprefix("series/").removeprefix("manga/").removeprefix("comics/")


def _chapter(value: str) -> str:
    value = str(value or "").strip("/").removeprefix("chapter/").removeprefix("reader/en/").split("/")[-1]
    return f"chapter-{value}" if value.isdigit() else value


def _number(value: str) -> str:
    match = re.search(r"chapter[-\s]+(\d+)(?:[.-](\d+))?$", str(value or "").strip().casefold())
    if match:
        return f"{int(match.group(1))}.{match.group(2)}" if match.group(2) else str(int(match.group(1)))
    value = str(value or "").strip()
    return value if re.fullmatch(r"\d+(?:\.\d+)?", value) else ""


def _ext(url: str) -> str:
    wrapped = parse_qs(urlparse(url).query).get("url", [])
    original = unquote(wrapped[0]) if wrapped else url
    extension = os.path.splitext(urlparse(original).path)[1].lower()
    return extension.lstrip(".") if extension in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"} else "webp"


class DuskDownloader:
    def __init__(self):
        self.api_url = DUSK_API.rstrip("/")

    async def search_manga(self, query: str) -> List[Dict[str, Any]]:
        async with _session() as session:
            data = await get_json(session, f"{self.api_url}/search", source="dusk", stage="search", params={"q": query}, timeout=6, validator=lambda p: isinstance(p.get("data"), list))
        return [{
            "id": _id(item.get("slug", item.get("id", ""))), "title": item.get("title", "Unknown"),
            "status": item.get("status", item.get("type_genre", "N/A")),
            "chapter_count": item.get("update", item.get("chapter_count", "N/A")),
            "rating": item.get("rating", "N/A"), "image": item.get("image", ""), "source": "dusk",
        } for item in (data or {}).get("data", []) if item.get("slug") or item.get("id")]

    async def get_manga_info(self, manga_id: str) -> Optional[Dict[str, Any]]:
        clean = _id(manga_id)
        async with _session() as session:
            data = await get_json(session, f"{self.api_url}/detail/{clean}", source="dusk", stage=f"detail:{clean}", timeout=6, validator=lambda p: bool((p.get("data") or p).get("chapters")))
        return (data.get("data") or data) if data else None

    async def get_chapter_list(self, manga_id: str) -> List[Dict[str, Any]]:
        info, clean = await self.get_manga_info(manga_id), _id(manga_id)
        return [{"id": _chapter(item.get("slug", item.get("title", ""))), "title": item.get("title", "Unknown Chapter"), "date": item.get("date", item.get("time", "")), "manga_id": clean, "source": "dusk", "locked": bool(item.get("locked"))} for item in (info or {}).get("chapters", []) if item.get("slug") or item.get("title")]

    async def get_chapter_images(self, manga_id: str, chapter_id: str) -> List[str]:
        manga, chapter = _id(manga_id), _chapter(chapter_id)
        requested = _number(chapter)
        if requested:
            chapters = await self.get_chapter_list(manga)
            matched = next((item for item in chapters if requested in {_number(item.get("id")), _number(item.get("title"))}), None)
            if matched:
                chapter = _chapter(matched["id"])
        async with _session() as session:
            data = await get_json(session, f"{self.api_url}/chapter/{manga}/{chapter}", source="dusk", stage=f"chapter:{manga}:{chapter}", timeout=10, validator=lambda p: bool((p.get("data") or p).get("images")))
        payload = (data or {}).get("data") or data or {}
        return [str(image).strip() for image in payload.get("images", []) if str(image).strip()]

    async def download_chapter(self, manga_id: str, chapter_id: str, save_dir: str) -> Optional[str]:
        images = await self.get_chapter_images(manga_id, chapter_id)
        if not images:
            return None
        target = os.path.join(save_dir, "dusk", f"{_id(manga_id)}_{_chapter(chapter_id)}")
        async with _session() as session:
            complete = await download_images(session, images, target, source="dusk", extension_for=_ext, concurrency=4, timeout=20)
        if complete:
            return target
        shutil.rmtree(target, ignore_errors=True)
        return None


dusk_downloader = DuskDownloader()


async def search_dusk(query: str):
    return await dusk_downloader.search_manga(query)

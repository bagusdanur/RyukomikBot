import os
import re
import shutil
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp

from config import VORTEX_API
from chapter_utils import normalize_chapter
from .retry import download_images, get_json

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def _session() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    return aiohttp.ClientSession(connector=connector, headers=HEADERS)


def _id(value: str) -> str:
    value = str(value or "").strip("/").removeprefix("series/").removeprefix("manga/")
    return value


def _chapter(value: str) -> str:
    value = str(value or "").strip("/").split("/")[-1]
    if value.isdigit():
        return f"chapter-{value}"
    return value


def _chapter_number(value: str) -> str:
    value = str(value or "").strip().casefold()
    match = re.search(r"chapter[-\s]+(\d+)(?:[.-](\d+))?$", value)
    if match:
        return f"{int(match.group(1))}.{match.group(2)}" if match.group(2) else str(int(match.group(1)))
    return value if re.fullmatch(r"\d+(?:\.\d+)?", value) else ""


def _ext(url: str) -> str:
    wrapped = parse_qs(urlparse(url).query).get("url", [])
    original = unquote(wrapped[0]) if wrapped else url
    extension = os.path.splitext(urlparse(original).path)[1].lower()
    return extension.lstrip(".") if extension in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else "webp"


class VortexDownloader:
    """Downloader for the Ryukomik Vortex Scans API."""

    def __init__(self):
        self.api_url = VORTEX_API.rstrip("/")

    async def search_manga(self, query: str) -> List[Dict[str, Any]]:
        async with _session() as session:
            data = await get_json(
                session,
                f"{self.api_url}/search",
                source="vortex",
                stage="search",
                params={"q": query},
                timeout=4,
                validator=lambda p: isinstance(p.get("data"), list),
            )
        if not data:
            return []
        return [
            {
                "id": _id(item.get("slug")),
                "title": item.get("title", "Unknown"),
                "status": item.get("type_genre", "N/A"),
                "chapter_count": item.get("update", "N/A"),
                "rating": item.get("rating", "N/A"),
                "image": item.get("image", ""),
                "source": "vortex",
            }
            for item in (data or {}).get("data", [])
            if item.get("slug")
        ]

    async def get_manga_info(self, manga_id: str) -> Optional[Dict[str, Any]]:
        clean_manga = _id(manga_id)
        async with _session() as session:
            data = await get_json(
                session,
                f"{self.api_url}/detail/{clean_manga}",
                source="vortex",
                stage=f"detail:{clean_manga}",
                timeout=5,
                validator=lambda p: bool((p.get("data") or {}).get("chapters")),
            )
        return data.get("data") if data else None

    async def get_chapter_list(self, manga_id: str) -> List[Dict[str, Any]]:
        info = await self.get_manga_info(manga_id)
        clean_manga = _id(manga_id)
        if not info:
            return []
        return [
            {
                "id": _chapter(chapter.get("slug", chapter.get("title", ""))),
                "title": chapter.get("title", "Unknown Chapter"),
                "date": chapter.get("date", chapter.get("time", "")),
                "manga_id": clean_manga,
                "source": "vortex",
                "locked": bool(chapter.get("locked")),
            }
            for chapter in info.get("chapters", [])
            if chapter.get("slug") or chapter.get("title")
        ]

    async def get_chapter_images(self, manga_id: str, chapter_id: str) -> List[str]:
        clean_manga = _id(manga_id)
        clean_chap = _chapter(chapter_id)
        requested_number = _chapter_number(clean_chap)
        needs_resolution = bool(re.fullmatch(r"(?:chapter[-\s]*)?\d+(?:[.-]\d+)?", clean_chap.casefold()))
        if requested_number and needs_resolution:
            chapters = await self.get_chapter_list(clean_manga)
            matched = next((
                chapter for chapter in chapters
                if requested_number in {
                    _chapter_number(chapter.get("id", "")),
                    _chapter_number(chapter.get("title", "")),
                }
            ), None)
            if matched and matched.get("id"):
                clean_chap = _chapter(matched["id"])

        async with _session() as session:
            data = await get_json(
                session,
                f"{self.api_url}/chapter/{clean_manga}/{clean_chap}",
                source="vortex",
                stage=f"chapter:{clean_manga}:{clean_chap}",
                timeout=10,
                validator=lambda p: bool(p.get("images")),
            )
        return [str(img).strip() for img in (data or {}).get("images", []) if str(img).strip()]

    async def download_chapter(self, manga_id: str, chapter_id: str, save_dir: str) -> Optional[str]:
        images = await self.get_chapter_images(manga_id, chapter_id)
        if not images:
            return None
        clean_manga = _id(manga_id)
        clean_chap = _chapter(chapter_id)
        target = os.path.join(save_dir, "vortex", f"{clean_manga}_{clean_chap}")
        async with _session() as session:
            ok = await download_images(
                session,
                images,
                target,
                source="vortex",
                extension_for=_ext,
                concurrency=4,
                timeout=20,
            )
        if ok:
            return target
        shutil.rmtree(target, ignore_errors=True)
        return None


vortex_downloader = VortexDownloader()


async def search_vortex(query: str) -> List[Dict[str, Any]]:
    return await vortex_downloader.search_manga(query)

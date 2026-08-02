import os
import shutil
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp

from config import SIREN_API
from .retry import get_bytes, get_json


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    )
}


def _create_session() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    return aiohttp.ClientSession(connector=connector, headers=DEFAULT_HEADERS)


def _clean_id(value: str) -> str:
    return str(value or "").strip("/").removeprefix("series/").removeprefix("manga/")


def _clean_chapter(value: str) -> str:
    value = str(value or "").strip("/").split("/")[-1]
    return f"chapter-{value}" if value.replace(".", "", 1).isdigit() else value


def _image_extension(url: str) -> str:
    wrapped = parse_qs(urlparse(url).query).get("url", [])
    original = unquote(wrapped[0]) if wrapped else url
    extension = os.path.splitext(urlparse(original).path)[1].lower()
    return extension.lstrip(".") if extension in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else "jpg"


class SirenDownloader:
    """Downloader for the Ryukomik Siren API schema."""

    def __init__(self):
        self.api_url = SIREN_API.rstrip("/")

    async def search_manga(self, query: str) -> List[Dict[str, Any]]:
        async with _create_session() as session:
            payload = await get_json(
                session, f"{self.api_url}/search", source="siren", stage="search",
                params={"q": query}, timeout=4,
                validator=lambda item: isinstance(item.get("data"), list),
            )
        if not payload:
            return []
        return [
            {
                "id": _clean_id(item.get("slug", item.get("id", ""))),
                "title": item.get("title", "Unknown"),
                "status": item.get("status", item.get("type_genre", "N/A")),
                "chapter_count": item.get("update", item.get("chapter_count", "N/A")),
                "rating": item.get("rating", "N/A"),
                "image": item.get("image", ""),
                "source": "siren",
            }
            for item in payload.get("data", [])
            if item.get("slug") or item.get("id")
        ]

    async def get_manga_info(self, manga_id: str) -> Optional[Dict[str, Any]]:
        clean_id = _clean_id(manga_id)
        async with _create_session() as session:
            payload = await get_json(
                session, f"{self.api_url}/detail/{clean_id}", source="siren",
                stage=f"detail:{clean_id}", timeout=4,
                validator=lambda item: bool((item.get("data") or item).get("chapters")),
            )
        return (payload.get("data", payload) if payload else None)

    async def get_chapter_list(self, manga_id: str) -> List[Dict[str, Any]]:
        info = await self.get_manga_info(manga_id)
        if not info:
            return []
        clean_id = _clean_id(manga_id)
        return [
            {
                "id": _clean_chapter(chapter.get("slug", chapter.get("title", ""))),
                "title": chapter.get("title", "Unknown Chapter"),
                "date": chapter.get("date", chapter.get("time", "")),
                "manga_id": clean_id,
                "source": "siren",
            }
            for chapter in info.get("chapters", [])
            if chapter.get("slug") or chapter.get("title")
        ]

    async def get_chapter_images(self, manga_id: str, chapter_id: str) -> List[str]:
        clean_manga, clean_chapter = _clean_id(manga_id), _clean_chapter(chapter_id)
        async with _create_session() as session:
            payload = await get_json(
                session, f"{self.api_url}/chapter/{clean_manga}/{clean_chapter}", source="siren",
                stage=f"chapter:{clean_manga}:{clean_chapter}", timeout=10,
                validator=lambda item: bool(item.get("images")),
            )
        if not payload:
            return []
        return [str(image).strip() for image in payload.get("images", []) if str(image).strip()]

    async def download_image(self, url: str, save_path: str) -> bool:
        async with _create_session() as session:
            content = await get_bytes(session, url, source="siren", stage=f"image:{os.path.basename(save_path)}")
        if not content:
            return False
        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as image_file:
                image_file.write(content)
            return True
        except OSError:
            return False

    async def download_chapter(self, manga_id: str, chapter_id: str, save_dir: str) -> Optional[str]:
        images = await self.get_chapter_images(manga_id, chapter_id)
        if not images:
            return None
        clean_manga, clean_chapter = _clean_id(manga_id), _clean_chapter(chapter_id)
        chapter_dir = os.path.join(save_dir, "siren", f"{clean_manga}_{clean_chapter}")
        downloaded = 0
        for index, url in enumerate(images, 1):
            if await self.download_image(url, os.path.join(chapter_dir, f"{index:03d}.{_image_extension(url)}")):
                downloaded += 1
        if downloaded == len(images):
            return chapter_dir
        shutil.rmtree(chapter_dir, ignore_errors=True)
        return None


siren_downloader = SirenDownloader()


async def search_siren(query: str) -> List[Dict[str, Any]]:
    return await siren_downloader.search_manga(query)

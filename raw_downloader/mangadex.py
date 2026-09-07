"""MangaDex API downloader for public chapter images."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .retry import download_images, get_json


API_URL = "https://api.mangadex.org"
HEADERS = {
    "User-Agent": "RyukomikBot/1.0 (https://github.com/bagusdanur/RyukomikBot)",
}


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(headers=HEADERS)


def _localized(values: dict[str, str] | None) -> str:
    values = values or {}
    for language in ("en", "id", "ja-ro", "ja"):
        if values.get(language):
            return values[language]
    return next(iter(values.values()), "Unknown")


def _extension(url: str) -> str:
    suffix = os.path.splitext(urlparse(url).path)[1].lower().lstrip(".")
    return suffix if suffix in {"jpg", "jpeg", "png", "webp", "gif"} else "jpg"


class MangaDexDownloader:
    async def search_manga(self, query: str) -> list[dict[str, Any]]:
        params = [("title", query), ("limit", "10"), ("includes[]", "cover_art")]
        async with _session() as session:
            payload = await get_json(
                session, f"{API_URL}/manga", source="mangadex", stage="search",
                params=params, timeout=10, validator=lambda item: isinstance(item.get("data"), list),
            )
        results = []
        for item in (payload or {}).get("data", []):
            attributes = item.get("attributes") or {}
            cover_name = ""
            for relation in item.get("relationships") or []:
                if relation.get("type") == "cover_art":
                    cover_name = (relation.get("attributes") or {}).get("fileName", "")
                    break
            manga_id = str(item.get("id") or "")
            results.append({
                "id": manga_id,
                "title": _localized(attributes.get("title")),
                "status": attributes.get("status", "N/A"),
                "chapter_count": "",
                "rating": "",
                "image": f"https://uploads.mangadex.org/covers/{manga_id}/{cover_name}.256.jpg" if cover_name else "",
                "source": "mangadex",
            })
        return results

    async def get_chapter_list(self, manga_id: str) -> list[dict[str, Any]]:
        chapters: list[dict[str, Any]] = []
        offset = 0
        async with _session() as session:
            while True:
                params = [
                    ("manga", manga_id), ("limit", "100"), ("offset", str(offset)),
                    ("order[chapter]", "desc"), ("includes[]", "scanlation_group"),
                    ("contentRating[]", "safe"), ("contentRating[]", "suggestive"),
                    ("contentRating[]", "erotica"), ("contentRating[]", "pornographic"),
                ]
                payload = await get_json(
                    session, f"{API_URL}/chapter", source="mangadex", stage=f"chapters:{offset}",
                    params=params, timeout=12, validator=lambda item: isinstance(item.get("data"), list),
                )
                if not payload:
                    break
                page = payload.get("data", [])
                for item in page:
                    attributes = item.get("attributes") or {}
                    number = attributes.get("chapter") or "Oneshot"
                    title = attributes.get("title")
                    language = attributes.get("translatedLanguage") or "?"
                    label = f"Chapter {number}" + (f" — {title}" if title else "") + f" [{language}]"
                    chapters.append({
                        "id": str(item.get("id") or ""), "title": label,
                        "date": attributes.get("publishAt") or attributes.get("updatedAt") or "",
                        "manga_id": manga_id, "source": "mangadex", "language": language,
                    })
                offset += len(page)
                if not page or offset >= int(payload.get("total") or 0):
                    break
        return chapters

    async def get_chapter_images(self, manga_id: str, chapter_id: str) -> list[str]:
        async with _session() as session:
            payload = await get_json(
                session, f"{API_URL}/at-home/server/{chapter_id}", source="mangadex",
                stage=f"chapter:{chapter_id}", timeout=12,
                validator=lambda item: bool(item.get("baseUrl") and (item.get("chapter") or {}).get("data")),
            )
        if not payload:
            return []
        chapter = payload["chapter"]
        base = payload["baseUrl"].rstrip("/")
        chapter_hash = chapter["hash"]
        return [f"{base}/data/{chapter_hash}/{name}" for name in chapter.get("data", [])]

    async def download_chapter(self, manga_id: str, chapter_id: str, save_dir: str, progress=None) -> str | None:
        images = await self.get_chapter_images(manga_id, chapter_id)
        if not images:
            return None
        target = os.path.join(save_dir, "mangadex", f"{manga_id}_{chapter_id}")
        async with _session() as session:
            complete = await download_images(
                session, images, target, source="mangadex", extension_for=_extension,
                progress=progress, concurrency=4, timeout=30, attempts=3,
            )
        return target if complete else None


mangadex_downloader = MangaDexDownloader()


async def search_mangadex(query: str):
    return await mangadex_downloader.search_manga(query)

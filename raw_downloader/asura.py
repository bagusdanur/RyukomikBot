import os
from typing import Any, Dict, List, Optional

import aiohttp

from config import ASURA_API


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
    value = value.strip("/")
    return value.removeprefix("manga/")


def _clean_chapter(value: str) -> str:
    value = value.strip("/").split("/")[-1]
    if value.isdigit():
        return f"chapter-{value}"
    return value


class AsuraDownloader:
    """Downloader matching the current Ryukomik Asura API schema."""

    def __init__(self):
        self.api_url = ASURA_API.rstrip("/")

    async def search_manga(self, query: str) -> List[Dict[str, Any]]:
        async with _create_session() as session:
            try:
                async with session.get(
                    f"{self.api_url}/search",
                    params={"q": query},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status != 200:
                        return []
                    payload = await response.json()
                    results = payload.get("data", payload.get("results", []))
                    return [
                        {
                            "id": _clean_id(item.get("slug", item.get("id", ""))),
                            "title": item.get("title", "Unknown"),
                            "status": item.get("status", "N/A"),
                            "chapter_count": item.get("update", item.get("chapter_count", "N/A")),
                            "rating": item.get("rating", "N/A"),
                            "image": item.get("image", ""),
                            "source": "asura",
                        }
                        for item in results
                    ]
            except (aiohttp.ClientError, TimeoutError, ValueError) as error:
                print(f"Error searching Asura manga: {error}")
                return []

    async def get_manga_info(self, manga_id: str) -> Optional[Dict[str, Any]]:
        async with _create_session() as session:
            try:
                async with session.get(
                    f"{self.api_url}/detail/{_clean_id(manga_id)}",
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status != 200:
                        return None
                    payload = await response.json()
                    return payload.get("data", payload)
            except (aiohttp.ClientError, TimeoutError, ValueError) as error:
                print(f"Error getting Asura manga info: {error}")
                return None

    async def get_chapter_list(self, manga_id: str) -> List[Dict[str, Any]]:
        info = await self.get_manga_info(manga_id)
        if not info:
            return []
        clean_manga = _clean_id(manga_id)
        return [
            {
                "id": _clean_chapter(chapter.get("slug", chapter.get("title", ""))),
                "title": chapter.get("title", "Unknown Chapter"),
                "date": chapter.get("date", ""),
                "manga_id": clean_manga,
                "source": "asura",
            }
            for chapter in info.get("chapters", [])
        ]

    async def get_chapter_images(self, manga_id: str, chapter_id: str) -> List[str]:
        clean_manga = _clean_id(manga_id)
        clean_chapter = _clean_chapter(chapter_id)
        async with _create_session() as session:
            try:
                async with session.get(
                    f"{self.api_url}/chapter/{clean_manga}/{clean_chapter}",
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        return []
                    payload = await response.json()
                    return payload.get("images", [])
            except (aiohttp.ClientError, TimeoutError, ValueError) as error:
                print(f"Error getting Asura chapter images: {error}")
                return []

    async def download_image(self, url: str, save_path: str) -> bool:
        async with _create_session() as session:
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status != 200:
                        return False
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    with open(save_path, "wb") as image_file:
                        image_file.write(await response.read())
                    return True
            except (aiohttp.ClientError, TimeoutError, OSError) as error:
                print(f"Error downloading Asura image: {error}")
                return False

    async def download_chapter(
        self, manga_id: str, chapter_id: str, save_dir: str
    ) -> Optional[str]:
        images = await self.get_chapter_images(manga_id, chapter_id)
        if not images:
            return None

        clean_manga = _clean_id(manga_id)
        clean_chapter = _clean_chapter(chapter_id)
        chapter_dir = os.path.join(save_dir, "asura", f"{clean_manga}_{clean_chapter}")
        downloaded = 0
        for index, url in enumerate(images, 1):
            extension = url.split("?")[0].rsplit(".", 1)[-1] if "." in url.split("?")[0] else "jpg"
            if await self.download_image(
                url, os.path.join(chapter_dir, f"{index:03d}.{extension}")
            ):
                downloaded += 1
        return chapter_dir if downloaded else None


downloader = AsuraDownloader()


async def search_asura(query: str) -> List[Dict[str, Any]]:
    return await downloader.search_manga(query)


async def get_chapter_images(manga_id: str, chapter_id: str) -> List[str]:
    return await downloader.get_chapter_images(manga_id, chapter_id)


async def download_chapter(
    manga_id: str, chapter_id: str, save_dir: str
) -> Optional[str]:
    return await downloader.download_chapter(manga_id, chapter_id, save_dir)

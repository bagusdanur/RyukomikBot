import aiohttp
import os
import shutil
from typing import Optional, Dict, List, Any
from urllib.parse import parse_qs, unquote, urlparse
from config import DOUJIVA_API
from .retry import get_bytes, get_json


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _create_session(headers: Optional[Dict[str, str]] = None) -> aiohttp.ClientSession:
    """Create a ClientSession using ThreadedResolver for reliable DNS resolution across environments."""
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    req_headers = DEFAULT_HEADERS.copy()
    if headers:
        req_headers.update(headers)
    return aiohttp.ClientSession(connector=connector, headers=req_headers)


def _clean_manga_id(manga_id: str) -> str:
    """Clean manga_id by removing leading 'manga/' if present."""
    manga_id = manga_id.strip("/")
    if manga_id.startswith("manga/"):
        return manga_id[6:]
    return manga_id


def _clean_chapter_id(chapter_id: str) -> str:
    """Clean chapter_id ensuring correct format (e.g., 'chapter-1' or '1')."""
    chapter_id = chapter_id.strip("/")
    if chapter_id.startswith("chapter-"):
        return chapter_id
    if chapter_id.isdigit():
        return f"chapter-{chapter_id}"
    return chapter_id


def _extract_image_url(image: Any) -> str:
    """Normalize API image entries that may be URLs or metadata objects."""
    if isinstance(image, str):
        return image.strip()
    if isinstance(image, dict):
        for key in ("url", "src", "image", "image_url"):
            value = image.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _original_image_url(url: str) -> str:
    """Return the upstream image URL when Doujiva wraps it in its proxy."""
    query_url = parse_qs(urlparse(url).query).get("url", [])
    return unquote(query_url[0]) if query_url else url


def _normalize_chapter_images(images: List[Any]) -> List[str]:
    """Keep the API array order: first item is page 1, second is page 2, etc."""
    normalized = []
    for image in images:
        url = _extract_image_url(image)
        if url:
            normalized.append(url)
    return normalized


def _image_extension(url: str) -> str:
    extension = os.path.splitext(urlparse(_original_image_url(url)).path)[1].lower()
    return extension.lstrip(".") if extension in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else "jpg"


class DoujivaDownloader:
    """Downloader for Doujiva manga / doujinshi chapters."""

    def __init__(self):
        self.api_url = DOUJIVA_API

    async def search_manga(self, query: str) -> List[Dict[str, Any]]:
        """Search for manga by title."""
        async with _create_session() as session:
            data = await get_json(session, f"{self.api_url}/search", source="doujiva", stage="search", params={"q": query}, timeout=4, validator=lambda item: bool(item.get("data")))
            if data:
                results = data.get("data", [])
                normalized = []
                for item in results:
                            raw_slug = item.get("slug", "")
                            clean_id = _clean_manga_id(raw_slug)
                            normalized.append({
                                "id": clean_id,
                                "title": item.get("title", "Unknown"),
                                "status": item.get("status", "N/A"),
                                "chapter_count": item.get("update", "N/A"),
                                "rating": item.get("rating", "N/A"),
                                "image": item.get("image", ""),
                                "source": "doujiva"
                            })
                return normalized
            return []

    async def get_manga_info(self, manga_id: str) -> Optional[Dict[str, Any]]:
        """Get manga information."""
        clean_id = _clean_manga_id(manga_id)
        async with _create_session() as session:
            data = await get_json(session, f"{self.api_url}/detail/{clean_id}", source="doujiva", stage=f"detail:{clean_id}", timeout=4, validator=lambda item: bool((item.get("data") or {}).get("chapters")))
            return data.get("data") if data else None

    async def get_chapter_list(self, manga_id: str) -> List[Dict[str, Any]]:
        """Get list of chapters for a manga."""
        info = await self.get_manga_info(manga_id)
        if not info or "chapters" not in info:
            return []

        clean_id = _clean_manga_id(manga_id)
        normalized_chapters = []
        for ch in info.get("chapters", []):
            raw_slug = ch.get("slug", "")
            parts = raw_slug.strip("/").split("/")
            chapter_id = parts[-1] if parts else ch.get("title", "")

            normalized_chapters.append({
                "id": chapter_id,
                "title": ch.get("title", f"Chapter {chapter_id}"),
                "date": ch.get("date", ""),
                "manga_id": clean_id,
                "source": "doujiva"
            })
        return normalized_chapters

    async def get_chapter_images(self, manga_id: str, chapter_id: str) -> List[str]:
        """Get image URLs for a specific chapter."""
        clean_manga = _clean_manga_id(manga_id)
        clean_chap = _clean_chapter_id(chapter_id)

        async with _create_session() as session:
            url = f"{self.api_url}/chapter/{clean_manga}/{clean_chap}"
            data = await get_json(session, url, source="doujiva", stage=f"chapter:{clean_manga}:{clean_chap}", timeout=10, validator=lambda item: bool(item.get("images")))
            if data:
                images = _normalize_chapter_images(data.get("images", []))
                if images:
                    return images
            url_fallback = f"{self.api_url}/chapter/manga/{clean_manga}/{clean_chap}"
            data = await get_json(session, url_fallback, source="doujiva", stage=f"chapter-fallback:{clean_manga}:{clean_chap}", timeout=10, validator=lambda item: bool(item.get("images")))
            return _normalize_chapter_images(data.get("images", [])) if data else []

    async def download_image(self, url: str, save_path: str) -> bool:
        """Download a single image."""
        async with _create_session() as session:
            try:
                content = await get_bytes(session, url, source="doujiva", stage=f"image:{os.path.basename(save_path)}")
                if not content:
                    return False
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(content)
                return True
            except OSError as e:
                print(f"Error downloading image from Doujiva: {e}")
                return False

    async def download_chapter(
        self,
        manga_id: str,
        chapter_id: str,
        save_dir: str
    ) -> Optional[str]:
        """Download all images in a chapter. Returns save directory path."""
        images = await self.get_chapter_images(manga_id, chapter_id)

        if not images:
            return None

        clean_manga = _clean_manga_id(manga_id)
        clean_chap = _clean_chapter_id(chapter_id)
        chapter_dir = os.path.join(save_dir, "doujiva", f"{clean_manga}_{clean_chap}")
        os.makedirs(chapter_dir, exist_ok=True)

        downloaded = 0
        for i, url in enumerate(images):
            ext = _image_extension(url)
            save_path = os.path.join(chapter_dir, f"{i+1:03d}.{ext}")

            if await self.download_image(url, save_path):
                downloaded += 1

        if downloaded == len(images):
            return chapter_dir
        shutil.rmtree(chapter_dir, ignore_errors=True)
        return None


# Global instance
doujiva_downloader = DoujivaDownloader()


async def search_doujiva(query: str) -> List[Dict[str, Any]]:
    """Search Doujiva for manga."""
    return await doujiva_downloader.search_manga(query)


async def get_doujiva_chapter_images(manga_id: str, chapter_id: str) -> List[str]:
    """Get chapter images from Doujiva."""
    return await doujiva_downloader.get_chapter_images(manga_id, chapter_id)


async def download_doujiva_chapter(manga_id: str, chapter_id: str, save_dir: str) -> Optional[str]:
    """Download a chapter from Doujiva."""
    return await doujiva_downloader.download_chapter(manga_id, chapter_id, save_dir)

import aiohttp
import os
from typing import Optional, Dict, List, Any
from config import DOUJIVA_API


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


class DoujivaDownloader:
    """Downloader for Doujiva manga / doujinshi chapters."""

    def __init__(self):
        self.api_url = DOUJIVA_API

    async def search_manga(self, query: str) -> List[Dict[str, Any]]:
        """Search for manga by title."""
        async with _create_session() as session:
            try:
                async with session.get(
                    f"{self.api_url}/search",
                    params={"q": query},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
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
            except Exception as e:
                print(f"Error searching Doujiva manga: {e}")
                return []

    async def get_manga_info(self, manga_id: str) -> Optional[Dict[str, Any]]:
        """Get manga information."""
        clean_id = _clean_manga_id(manga_id)
        async with _create_session() as session:
            try:
                async with session.get(
                    f"{self.api_url}/detail/{clean_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("data")
                    return None
            except Exception as e:
                print(f"Error getting Doujiva manga info: {e}")
                return None

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
            try:
                url = f"{self.api_url}/chapter/{clean_manga}/{clean_chap}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("images", [])

                url_fallback = f"{self.api_url}/chapter/manga/{clean_manga}/{clean_chap}"
                async with session.get(url_fallback, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("images", [])

                return []
            except Exception as e:
                print(f"Error getting Doujiva chapter images: {e}")
                return []

    async def download_image(self, url: str, save_path: str) -> bool:
        """Download a single image."""
        async with _create_session() as session:
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        os.makedirs(os.path.dirname(save_path), exist_ok=True)
                        with open(save_path, "wb") as f:
                            f.write(await response.read())
                        return True
                    return False
            except Exception as e:
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
            ext = "jpg"
            if "." in url.split("?")[0]:
                ext = url.split("?")[0].split(".")[-1]
            save_path = os.path.join(chapter_dir, f"{i+1:03d}.{ext}")

            if await self.download_image(url, save_path):
                downloaded += 1

        if downloaded > 0:
            return chapter_dir
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

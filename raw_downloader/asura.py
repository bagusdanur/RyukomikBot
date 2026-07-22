import aiohttp
import os
from typing import Optional, Dict, List, Any
from config import ASURA_API


def _create_session() -> aiohttp.ClientSession:
    """Create a ClientSession using ThreadedResolver for reliable DNS resolution across environments."""
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    return aiohttp.ClientSession(connector=connector)


class AsuraDownloader:
    """Downloader for Asura Scans manga chapters."""
    
    def __init__(self):
        self.api_url = ASURA_API
    
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
                        return data.get("results", [])
                    return []
            except Exception as e:
                print(f"Error searching manga: {e}")
                return []
    
    async def get_manga_info(self, manga_id: str) -> Optional[Dict[str, Any]]:
        """Get manga information."""
        async with _create_session() as session:
            try:
                async with session.get(
                    f"{self.api_url}/manga/{manga_id}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
            except Exception as e:
                print(f"Error getting manga info: {e}")
                return None
    
    async def get_chapter_list(self, manga_id: str) -> List[Dict[str, Any]]:
        """Get list of chapters for a manga."""
        async with _create_session() as session:
            try:
                async with session.get(
                    f"{self.api_url}/manga/{manga_id}/chapters",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("chapters", [])
                    return []
            except Exception as e:
                print(f"Error getting chapter list: {e}")
                return []
    
    async def get_chapter_images(self, manga_id: str, chapter_id: str) -> List[str]:
        """Get image URLs for a specific chapter."""
        async with _create_session() as session:
            try:
                async with session.get(
                    f"{self.api_url}/manga/{manga_id}/chapter/{chapter_id}",
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("images", [])
                    return []
            except Exception as e:
                print(f"Error getting chapter images: {e}")
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
                print(f"Error downloading image: {e}")
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
        
        chapter_dir = os.path.join(save_dir, "asura", f"{manga_id}_{chapter_id}")
        os.makedirs(chapter_dir, exist_ok=True)
        
        downloaded = 0
        for i, url in enumerate(images):
            ext = url.split(".")[-1].split("?")[0]
            save_path = os.path.join(chapter_dir, f"{i+1:03d}.{ext}")
            
            if await self.download_image(url, save_path):
                downloaded += 1
        
        if downloaded > 0:
            return chapter_dir
        return None


# Global instance
downloader = AsuraDownloader()


async def search_asura(query: str) -> List[Dict[str, Any]]:
    """Search Asura Scans for manga."""
    return await downloader.search_manga(query)


async def get_chapter_images(manga_id: str, chapter_id: str) -> List[str]:
    """Get chapter images from Asura Scans."""
    return await downloader.get_chapter_images(manga_id, chapter_id)


async def download_chapter(manga_id: str, chapter_id: str, save_dir: str) -> Optional[str]:
    """Download a chapter from Asura Scans."""
    return await downloader.download_chapter(manga_id, chapter_id, save_dir)

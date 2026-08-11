import re

from .qimanga import QiMangaDownloader
from config import DEMON_API
from chapter_utils import normalize_chapter

class DemonDownloader(QiMangaDownloader):
    def __init__(self): self.api_url = DEMON_API.rstrip("/")
    async def search_manga(self, query):
        rows = await super().search_manga(query)
        for row in rows:
            row["id"] = row["id"].removeprefix("manga/")
            row["source"] = "demon"
        return rows
    async def get_manga_info(self, manga_id): return await super().get_manga_info(str(manga_id).removeprefix("manga/"))
    async def get_chapter_list(self, manga_id):
        rows = await super().get_chapter_list(str(manga_id).removeprefix("manga/"))
        for row in rows: row["source"] = "demon"
        return rows
    async def get_chapter_images(self, manga_id, chapter_id):
        manga_id = str(manga_id).removeprefix("manga/")
        raw_chapter_id = str(chapter_id).strip().strip('/')
        # Opaque Demon slugs (for example 12903-50) must not be normalized:
        # normalization turns them into 12903 and can select a wrong chapter.
        if re.fullmatch(r'\d+-\d+(?:\.\d+)?', raw_chapter_id):
            return await super().get_chapter_images(manga_id, raw_chapter_id)

        wanted = normalize_chapter(raw_chapter_id)
        if wanted:
            chapters = await self.get_chapter_list(manga_id)
            matched = next((item for item in chapters if wanted in {
                normalize_chapter(str(item.get("id", ""))),
                normalize_chapter(str(item.get("title", ""))),
            }), None)
            if matched:
                chapter_id = matched["id"]
        return await super().get_chapter_images(manga_id, chapter_id)

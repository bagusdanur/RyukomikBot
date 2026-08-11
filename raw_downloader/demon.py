from .qimanga import QiMangaDownloader
from config import DEMON_API

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
    async def get_chapter_images(self, manga_id, chapter_id): return await super().get_chapter_images(str(manga_id).removeprefix("manga/"), chapter_id)

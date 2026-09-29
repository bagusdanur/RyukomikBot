from config import MIST_API
from .dusk import DuskDownloader


class MistDownloader(DuskDownloader):
    """Downloader for Mist Scans chapters through the Ryukomik API.

    Mist numbers its chapters on the detail payload ("Chapter 40"), but the
    API addresses them by an opaque per-chapter hash
    (``64f6dd0cdf8-65bb0190b9c``) which does not contain the number.  The
    shared DuskDownloader flow asks for a numeric chapter and then tries to
    match that number against the chapter list, which cannot resolve a hash --
    so this downloader keeps the slug exactly as the caller supplied it and
    lets the API resolve it.
    """

    def __init__(self):
        super().__init__(MIST_API, "mist")

    async def get_chapter_images(self, manga_id, chapter_id):
        chapter = str(chapter_id or "").strip().strip("/")
        if not chapter:
            return []
        return await super().get_chapter_images(manga_id, chapter)


mist_downloader = MistDownloader()


async def search_mist(query: str):
    return await mist_downloader.search_manga(query)

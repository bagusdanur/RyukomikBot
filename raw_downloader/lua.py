from config import LUA_API
from .dusk import DuskDownloader, _id, _session
from .retry import get_json


class LuaDownloader(DuskDownloader):
    """Downloader for free/public Lua Comic chapters through Ryukomik API."""

    def __init__(self):
        super().__init__(LUA_API, "lua")

    async def get_manga_info(self, manga_id):
        """Lua's complete chapter catalogue can be slow on the first uncached call."""
        clean = _id(manga_id)
        async with _session() as session:
            data = await get_json(
                session,
                f"{self.api_url}/detail/{clean}",
                source=self.source,
                stage=f"detail:{clean}",
                timeout=35,
                validator=lambda payload: bool((payload.get("data") or payload).get("chapters")),
            )
        return (data.get("data") or data) if data else None


lua_downloader = LuaDownloader()


async def search_lua(query: str):
    return await lua_downloader.search_manga(query)

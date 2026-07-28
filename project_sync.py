"""Low-egress Project Ryukomik event sync for Discord announcements."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import discord

from config import NEW_PROJECT_CHANNEL_ID, PROJECT_DROP_CHANNEL_ID, PROJECT_EVENTS_TOKEN, PROJECT_EVENTS_URL, PROJECT_PUBLIC_URL, UPDATE_PROJECT_CHANNEL_ID
from database import get_db

log = logging.getLogger(__name__)


async def setup_project_sync() -> None:
    db = await get_db()
    try:
        await db.execute("""CREATE TABLE IF NOT EXISTS project_discord_sync (
            event_id INTEGER PRIMARY KEY, event_type TEXT NOT NULL,
            message_id INTEGER, delivered_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.commit()
    finally:
        await db.close()


async def _last_event_id() -> int:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT COALESCE(MAX(event_id),0) AS event_id FROM project_discord_sync")).fetchone()
        return int(row["event_id"])
    finally:
        await db.close()


async def _record_delivery(event: dict[str, Any], message_id: int) -> None:
    db = await get_db()
    try:
        await db.execute("INSERT OR IGNORE INTO project_discord_sync(event_id,event_type,message_id) VALUES(?,?,?)", (int(event["id"]), str(event["event_type"]), message_id))
        await db.commit()
    finally:
        await db.close()


def _project_url(payload: dict[str, Any]) -> str:
    slug = str(payload.get("slug") or "").strip("/")
    return f"{PROJECT_PUBLIC_URL}/komik/project/{slug}" if slug else PROJECT_PUBLIC_URL


def build_project_embed(event: dict[str, Any]) -> tuple[int, discord.Embed, discord.ui.View]:
    payload = event.get("payload") or {}
    title = str(payload.get("title") or "Project Ryukomik")
    status = str(payload.get("status") or "-").capitalize()
    event_type = event.get("event_type")
    if event_type == "project_published":
        channel_id, heading, color = NEW_PROJECT_CHANNEL_ID, "Project Baru", discord.Color.blurple()
        description = f"**{title}** resmi masuk ke project Ryukomik."
    elif event_type == "chapter_published":
        channel_id, heading, color = UPDATE_PROJECT_CHANNEL_ID, "Project Update", discord.Color.green()
        chapter = payload.get("chapter_number")
        description = f"**{title}** — **{'Chapter ' + str(chapter) if chapter is not None else 'Chapter terbaru'}** telah dirilis."
        if payload.get("chapter_title"):
            description += f"\n{str(payload['chapter_title']).strip()}"
    elif event_type == "project_status_changed":
        channel_id = PROJECT_DROP_CHANNEL_ID
        cancelled = str(payload.get("status") or "").casefold() == "cancelled"
        heading = "Project Dibatalkan" if cancelled else "Project Dihentikan"
        color = discord.Color.red() if cancelled else discord.Color.orange()
        description = f"**{title}** berstatus **{status}**."
    else:
        raise ValueError(f"Unsupported project event: {event_type}")
    embed = discord.Embed(title=heading, description=description, color=color)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Tipe", value=str(payload.get("type") or "-").upper(), inline=True)
    genres = payload.get("genres") or []
    if genres:
        embed.add_field(name="Genre", value=", ".join(map(str, genres))[:1024], inline=False)
    cover_url = str(payload.get("cover_url") or "")
    if cover_url.startswith(("https://", "http://")):
        embed.set_thumbnail(url=cover_url)
    embed.set_footer(text="Ryukomik Official • Informasi project")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Buka Project", style=discord.ButtonStyle.link, url=_project_url(payload)))
    return channel_id, embed, view


async def sync_project_events(guild: discord.Guild) -> int:
    if not PROJECT_EVENTS_TOKEN:
        return 0
    after = await _last_event_id()
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(PROJECT_EVENTS_URL, params={"after": after, "limit": 25}, headers={"Authorization": f"Bearer {PROJECT_EVENTS_TOKEN}"}) as response:
            if response.status != 200:
                raise RuntimeError(f"Project event API HTTP {response.status}")
            body = await response.json(content_type=None)
    events = body.get("data")
    if not isinstance(events, list):
        raise RuntimeError("Project event API returned malformed data")
    delivered = 0
    for event in events:
        channel_id, embed, view = build_project_embed(event)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"Project announcement channel unavailable: {channel_id}")
        message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        await _record_delivery(event, message.id)
        delivered += 1
    return delivered

"""Low-egress Project Ryukomik event sync for Discord announcements."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import discord

from config import NEW_PROJECT_CHANNEL_ID, PROJECT_DROP_CHANNEL_ID, PROJECT_EVENTS_TOKEN, PROJECT_EVENTS_URL, PROJECT_PUBLIC_URL, ROLE_NOTIFICATION_ID, ROLE_NOTIFICATION_NAME, SCANLATOR_UPDATE_CHANNEL_ID, UPDATE_PROJECT_CHANNEL_ID
from database import get_db

log = logging.getLogger(__name__)

# Tipe event yang layak menandai @everyone. Update chapter sengaja hanya
# menyebut role, supaya channel tidak berisik tiap ada chapter baru.
EVERYONE_EVENT_TYPES = {"project_published", "scanlator_series_published"}


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


def _chapter_url(payload: dict[str, Any]) -> str:
    slug = str(payload.get("slug") or "").strip("/")
    number = payload.get("chapter_number")
    if slug and number is not None:
        return f"{PROJECT_PUBLIC_URL}/chapter/project/{slug}/chapter-{number}"
    return _project_url(payload)


def _team_label(payload: dict[str, Any]) -> str:
    return str(payload.get("scanlator_team") or payload.get("scanlator_handle") or "Scanlator")


def _chapter_title_suffix(payload: dict[str, Any]) -> str:
    """Baris judul chapter, dilewati kalau isinya cuma "Chapter <nomor>"."""
    raw = str(payload.get("chapter_title") or "").strip()
    if not raw:
        return ""
    number = payload.get("chapter_number")
    if number is not None:
        normalized = raw.casefold()
        generic = {
            f"chapter {number}".casefold(),
            f"chapter {number}.0".casefold(),
            f"ch. {number}".casefold(),
            f"ch {number}".casefold(),
        }
        if normalized in generic:
            return ""
    return f"\n{raw}"


def build_project_embed(event: dict[str, Any]) -> tuple[int, discord.Embed, discord.ui.View]:
    payload = event.get("payload") or {}
    title = str(payload.get("title") or "Project Ryukomik")
    status = str(payload.get("status") or "-").capitalize()
    event_type = event.get("event_type")
    if event_type == "project_published":
        channel_id, heading, color = NEW_PROJECT_CHANNEL_ID, "Project Baru", discord.Color.blurple()
        description = f"**{title}** resmi masuk ke project Ryukomik."
        link = _project_url(payload)
    elif event_type == "chapter_published":
        channel_id, heading, color = UPDATE_PROJECT_CHANNEL_ID, "Project Update", discord.Color.green()
        chapter = payload.get("chapter_number")
        description = f"**{title}** — **{'Chapter ' + str(chapter) if chapter is not None else 'Chapter terbaru'}** telah dirilis."
        description += _chapter_title_suffix(payload)
        link = _chapter_url(payload)
    elif event_type == "scanlator_series_published":
        team = _team_label(payload)
        handle = str(payload.get("scanlator_handle") or "")
        channel_id, heading, color = SCANLATOR_UPDATE_CHANNEL_ID or UPDATE_PROJECT_CHANNEL_ID, "Project Baru", discord.Color.blurple()
        description = f"**{title}** resmi masuk ke project Ryukomik."
        description += f"\noleh **{team}**" + (f" (@{handle})" if handle else "")
        link = _project_url(payload)
    elif event_type == "scanlator_chapter_published":
        team = _team_label(payload)
        handle = str(payload.get("scanlator_handle") or "")
        channel_id, heading, color = SCANLATOR_UPDATE_CHANNEL_ID or UPDATE_PROJECT_CHANNEL_ID, "Project Update", discord.Color.green()
        chapter = payload.get("chapter_number")
        description = f"**{title}** — **{'Chapter ' + str(chapter) if chapter is not None else 'Chapter terbaru'}** telah dirilis."
        description += _chapter_title_suffix(payload)
        description += f"\noleh **{team}**" + (f" (@{handle})" if handle else "")
        link = _chapter_url(payload)
    elif event_type == "project_status_changed":
        channel_id = PROJECT_DROP_CHANNEL_ID
        cancelled = str(payload.get("status") or "").casefold() == "cancelled"
        heading = "Project Dibatalkan" if cancelled else "Project Dihentikan"
        color = discord.Color.red() if cancelled else discord.Color.orange()
        description = f"**{title}** berstatus **{status}**."
        link = _project_url(payload)
    else:
        raise ValueError(f"Unsupported project event: {event_type}")
    embed = discord.Embed(title=heading, description=description, color=color)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Tipe", value=str(payload.get("type") or "-").upper(), inline=True)
    # Sinopsis hanya untuk pengumuman seri baru — di update chapter bikin pesan
    # kepanjangan (permintaan user).
    if event_type in {"project_published", "scanlator_series_published"}:
        synopsis = " ".join(str(payload.get("description") or "").split())
        if synopsis:
            embed.add_field(name="Sinopsis", value=(synopsis[:400] + "…") if len(synopsis) > 400 else synopsis, inline=False)
    genres = payload.get("genres") or []
    if genres:
        embed.add_field(name="Genre", value=", ".join(map(str, genres))[:1024], inline=False)
    cover_url = str(payload.get("cover_url") or "")
    if cover_url.startswith(("https://", "http://")):
        embed.set_thumbnail(url=cover_url)
    embed.set_footer(text="Ryukomik Official • Informasi project")
    view = discord.ui.View()
    chapter_event = event_type in {"chapter_published", "scanlator_chapter_published"}
    view.add_item(
        discord.ui.Button(
            label="Baca Chapter" if chapter_event else "Buka Project",
            style=discord.ButtonStyle.link,
            url=link,
        )
    )
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
    notification_role = guild.get_role(ROLE_NOTIFICATION_ID) if ROLE_NOTIFICATION_ID else None
    notification_role = notification_role or discord.utils.get(guild.roles, name=ROLE_NOTIFICATION_NAME)
    for event in events:
        event_type = event.get("event_type")
        mentions: list[str] = ["@everyone"] if event_type in EVERYONE_EVENT_TYPES else []
        if notification_role:
            mentions.append(notification_role.mention)
        try:
            channel_id, embed, view = build_project_embed(event)
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                raise RuntimeError(f"Project announcement channel unavailable: {channel_id}")
            message = await channel.send(
                content=" ".join(mentions) or None,
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(
                    everyone="@everyone" in mentions,
                    users=False,
                    roles=[notification_role] if notification_role else False,
                ),
            )
        except Exception as error:  # noqa: BLE001 - satu event gagal tidak boleh memblokir antrean
            log.warning("Project event %s gagal dikirim: %s", event.get("id"), error)
            print(f"[PROJECT] Event {event.get('id')} gagal: {error}", flush=True)
            # message_id 0 = sudah diproses tapi tidak terkirim; antrean lanjut.
            await _record_delivery(event, 0)
            continue
        await _record_delivery(event, message.id)
        delivered += 1
    return delivered

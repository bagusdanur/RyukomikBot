"""Discord bridge for the Yuki companion service on the same VPS."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import aiohttp
import discord
import database as db_module

YUKI_API_URL = os.getenv("YUKI_API_URL", "http://127.0.0.1:3025").rstrip("/")
YUKI_CHANNEL_NAME = os.getenv("YUKI_DISCORD_CHANNEL", "🌸・yuki-ai")
COOLDOWN_SECONDS = max(2, int(os.getenv("YUKI_DISCORD_COOLDOWN", "8")))
_last_message: dict[int, float] = {}
_locks: dict[int, asyncio.Lock] = {}


class YukiServiceError(RuntimeError):
    pass


async def setup_yuki_tables() -> None:
    connection = await db_module.get_db()
    try:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS yuki_discord_sessions (
                discord_user_id INTEGER PRIMARY KEY,
                yuki_user_id TEXT NOT NULL,
                access_code TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await connection.commit()
    finally:
        await connection.close()


async def ensure_yuki_channel(guild: discord.Guild) -> discord.TextChannel:
    existing = discord.utils.get(guild.text_channels, name=YUKI_CHANNEL_NAME)
    if existing:
        return existing
    channel = await guild.create_text_channel(
        YUKI_CHANNEL_NAME,
        topic="Ngobrol langsung dengan Yuki AI. Gunakan /yuki-reset untuk memulai percakapan baru.",
        reason="Membuat ruang khusus Yuki AI",
    )
    embed = discord.Embed(
        title="🌸 Selamat datang di ruang Yuki",
        description=("Kirim pesan biasa di sini dan Yuki akan membalasmu. Memori dipisahkan untuk "
                     "setiap pengguna.\n\nGunakan `/yuki-reset` untuk memulai dari awal dan "
                     "`/yuki-status` untuk mengecek layanan."),
        color=discord.Color.from_rgb(244, 143, 177),
    )
    message = await channel.send(embed=embed)
    try:
        await message.pin(reason="Panduan ruang Yuki AI")
    except discord.HTTPException:
        pass
    return channel


def is_yuki_channel(channel: Any) -> bool:
    return isinstance(channel, discord.TextChannel) and channel.name == YUKI_CHANNEL_NAME


async def _stored_session(discord_user_id: int) -> dict[str, str] | None:
    connection = await db_module.get_db()
    try:
        row = await (await connection.execute(
            "SELECT yuki_user_id, access_code FROM yuki_discord_sessions WHERE discord_user_id=?",
            (discord_user_id,),
        )).fetchone()
        return dict(row) if row else None
    finally:
        await connection.close()


async def _save_session(discord_user_id: int, user_id: str, access_code: str) -> None:
    connection = await db_module.get_db()
    try:
        await connection.execute(
            """INSERT INTO yuki_discord_sessions(discord_user_id,yuki_user_id,access_code)
               VALUES(?,?,?) ON CONFLICT(discord_user_id) DO UPDATE SET
               yuki_user_id=excluded.yuki_user_id, access_code=excluded.access_code,
               updated_at=CURRENT_TIMESTAMP""",
            (discord_user_id, user_id, access_code),
        )
        await connection.commit()
    finally:
        await connection.close()


async def _delete_session(discord_user_id: int) -> None:
    connection = await db_module.get_db()
    try:
        await connection.execute("DELETE FROM yuki_discord_sessions WHERE discord_user_id=?", (discord_user_id,))
        await connection.commit()
    finally:
        await connection.close()


async def _json(session: aiohttp.ClientSession, method: str, path: str, **kwargs) -> dict[str, Any]:
    try:
        async with session.request(method, f"{YUKI_API_URL}{path}", timeout=aiohttp.ClientTimeout(total=45), **kwargs) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise YukiServiceError(str(payload.get("error") or f"HTTP {response.status}"))
            return payload
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        raise YukiServiceError("Layanan Yuki sedang tidak merespons.") from error


async def _login_or_register(session: aiohttp.ClientSession, member: discord.Member) -> dict[str, Any]:
    stored = await _stored_session(member.id)
    if stored:
        try:
            return await _json(session, "POST", "/api/login-code", json={"accessCode": stored["access_code"]})
        except YukiServiceError:
            await _delete_session(member.id)
    registered = await _json(session, "POST", "/api/register", json={"username": member.display_name[:50]})
    await _save_session(member.id, str(registered["userId"]), str(registered["accessCode"]))
    return registered


async def chat_with_yuki(member: discord.Member, text: str) -> dict[str, Any]:
    lock = _locks.setdefault(member.id, asyncio.Lock())
    if lock.locked():
        raise YukiServiceError("Pesanmu sebelumnya masih diproses. Tunggu balasan Yuki dulu, ya.")
    remaining = COOLDOWN_SECONDS - (time.monotonic() - _last_message.get(member.id, 0))
    if remaining > 0:
        raise YukiServiceError(f"Tunggu {max(1, round(remaining))} detik sebelum mengirim pesan lagi.")
    _last_message[member.id] = time.monotonic()
    async with lock, aiohttp.ClientSession() as session:
        identity = await _login_or_register(session, member)
        history = [{"role": item.get("role"), "content": item.get("content")}
                   for item in (identity.get("history") or [])[-29:]
                   if item.get("role") in {"user", "assistant"} and item.get("content")]
        history.append({"role": "user", "content": text[:4000]})
        return await _json(
            session, "POST", "/api/chat",
            headers={"Authorization": f"Bearer {identity['sessionToken']}"},
            json={"messages": history, "mode": "companion", "surface": "discord",
                  "username": member.display_name[:50]},
        )


async def reset_yuki(member: discord.Member) -> bool:
    stored = await _stored_session(member.id)
    if not stored:
        return False
    async with aiohttp.ClientSession() as session:
        try:
            identity = await _json(session, "POST", "/api/login-code", json={"accessCode": stored["access_code"]})
            await _json(session, "DELETE", "/api/account",
                        headers={"Authorization": f"Bearer {identity['sessionToken']}"})
        finally:
            await _delete_session(member.id)
    return True


async def yuki_health() -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            return (await _json(session, "GET", "/api/health")).get("status") == "ok"
    except YukiServiceError:
        return False


MOOD_COLORS = {"senang": 0xF48FB1, "malu": 0xCE93D8, "sedih": 0x90CAF9,
               "kesal": 0xEF9A9A, "marah": 0xE57373, "tenang": 0x80CBC4,
               "cemas": 0xFFCC80, "cemburu": 0xB39DDB}


def response_embeds(payload: dict[str, Any]) -> list[discord.Embed]:
    reply = str(payload.get("reply") or "...").strip()
    comics = [item for item in (payload.get("comics") or []) if item.get("title") and item.get("url")][:6]
    if comics:
        positions = [reply.casefold().find(str(item["title"]).casefold()) for item in comics]
        positions = [position for position in positions if position >= 0]
        if positions:
            reply = reply[:min(positions)].rstrip(" \n:-*#")
        if len(reply) < 8:
            reply = "Aku menemukan beberapa komik yang mungkin cocok untukmu. Pilih yang menarik, ya."
    chunks = [reply[index:index + 3900] for index in range(0, len(reply), 3900)] or ["..."]
    mood = str(payload.get("mood") or "tenang").casefold()
    embeds = []
    for index, chunk in enumerate(chunks):
        embed = discord.Embed(description=chunk, color=MOOD_COLORS.get(mood, 0xF48FB1))
        embed.set_author(name="Yuki 🌸")
        if index == len(chunks) - 1:
            embed.set_footer(text=f"Mood: {mood.title()} • Kedekatan: {payload.get('bond') or 'kenalan'}")
        embeds.append(embed)
    for index, comic in enumerate(comics, 1):
        card = discord.Embed(
            title=str(comic.get("title") or "Komik")[:256],
            url=str(comic.get("url") or ""),
            description="Klik judul atau tombol **Baca sekarang** untuk membuka komik di Ryukomik.",
            color=0xE85D75,
        )
        image = str(comic.get("image") or "")
        if image.startswith(("https://", "http://")):
            card.set_thumbnail(url=image)
        card.add_field(name="Format", value=str(comic.get("format") or "Komik").title(), inline=True)
        card.add_field(name="Genre", value=str(comic.get("type") or "Belum tersedia")[:1024], inline=True)
        card.add_field(name="Chapter terbaru", value=str(comic.get("chapter") or "Belum tersedia")[:1024], inline=True)
        if comic.get("score"):
            card.add_field(name="Rating", value=f"⭐ {comic['score']}", inline=True)
        card.set_footer(text=f"Rekomendasi {index} dari {len(comics)} • Ryukomik")
        embeds.append(card)
    return embeds


def response_view(payload: dict[str, Any]) -> discord.ui.View | None:
    comics = [item for item in (payload.get("comics") or []) if item.get("title") and item.get("url")][:6]
    if not comics:
        return None
    view = discord.ui.View(timeout=300)
    for index, comic in enumerate(comics):
        view.add_item(discord.ui.Button(
            label=f"Baca {str(comic['title'])[:70]}", url=str(comic["url"]), emoji="📖", row=index // 5,
        ))
    return view

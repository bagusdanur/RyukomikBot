"""Giveaway business logic, duration parsing, embed builders, and winner resolution for Ryukomik."""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Sequence

import discord
from discord.ext import commands

import database as db
from config import DASHBOARD_URL, ROLE_ADMIN_ID

log = logging.getLogger(__name__)

# Ryukomik Premium Preset Names
PREMIUM_3D = "Ryukomik Premium 3 Hari"
PREMIUM_7D = "Ryukomik Premium 7 Hari"
PREMIUM_30D = "Ryukomik Premium 30 Hari (1 Bulan)"

PRESET_PRIZES = (
    PREMIUM_3D,
    PREMIUM_7D,
    PREMIUM_30D,
)

SUGGESTED_PRIZES = (
    "💎 Ryukomik Premium 7 Hari",
    "👑 Ryukomik Premium 30 Hari (1 Bulan)",
    "🌟 Ryukomik Premium 3 Hari",
    "💎 5x Ryukomik Premium 7 Hari",
    "👑 3x Ryukomik Premium 30 Hari",
    "🌟 5x Ryukomik Premium 3 Hari",
    "💎 10x Ryukomik Premium 7 Hari",
    "🎁 Akses VIP Ryukomik 1 Bulan",
)

DURATION_PRESETS = (
    ("⏱️ 15 Menit", "15 menit"),
    ("⏱️ 30 Menit", "30 menit"),
    ("⏱️ 1 Jam", "1 jam"),
    ("⏱️ 2 Jam", "2 jam"),
    ("⏱️ 3 Jam", "3 jam"),
    ("⏱️ 6 Jam", "6 jam"),
    ("⏱️ 12 Jam", "12 jam"),
    ("⏱️ 1 Hari (24 Jam)", "1 hari"),
    ("⏱️ 2 Hari", "2 hari"),
    ("⏱️ 3 Hari", "3 hari"),
    ("⏱️ 7 Hari (1 Minggu)", "7 hari"),
)

_UNIT_MAP = {
    # Seconds / Detik
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "detik": 1,
    "dtk": 1,
    # Minutes / Menit
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "menit": 60,
    "mnt": 60,
    # Hours / Jam
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "jam": 3600,
    "jm": 3600,
    "j": 3600,
    # Days / Hari
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "hari": 86400,
    "hri": 86400,
    # Weeks / Minggu
    "w": 7 * 86400,
    "wk": 7 * 86400,
    "wks": 7 * 86400,
    "week": 7 * 86400,
    "weeks": 7 * 86400,
    "minggu": 7 * 86400,
    "mgg": 7 * 86400,
    # Months / Bulan (~30 days)
    "mo": 30 * 86400,
    "month": 30 * 86400,
    "months": 30 * 86400,
    "bulan": 30 * 86400,
    "bln": 30 * 86400,
}

_DURATION_TOKEN_REGEX = re.compile(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)")


def parse_duration(duration_str: str) -> int:
    """
    Parse duration string into total seconds.
    Supports Indonesian phrases (e.g. '2 jam', '30 menit', '1 hari 2 jam', '1 minggu', '1 bulan')
    as well as standard short codes (e.g. '30s', '10m', '2h', '3d', '7d', '1w').
    Returns 0 if duration string is invalid.
    """
    if not duration_str:
        return 0
    cleaned = duration_str.strip().casefold()
    if not cleaned or "-" in cleaned:
        return 0

    matches = _DURATION_TOKEN_REGEX.findall(cleaned)
    if not matches:
        return 0

    # Ensure no unrecognized word tokens exist in string
    reconstructed = _DURATION_TOKEN_REGEX.sub("", cleaned)
    reconstructed_clean = re.sub(r"[\s,\+&]|dan", "", reconstructed)
    if reconstructed_clean:
        return 0

    total_seconds = 0.0
    for value_str, unit_str in matches:
        unit = unit_str.casefold()
        if unit not in _UNIT_MAP:
            return 0
        try:
            val = float(value_str)
            if val < 0:
                return 0
            total_seconds += val * _UNIT_MAP[unit]
        except ValueError:
            return 0

    return int(total_seconds)


def format_duration_id(total_seconds: int) -> str:
    """Format duration in seconds to natural Indonesian text."""
    if total_seconds <= 0:
        return "0 Detik"
    days = total_seconds // 86400
    remainder = total_seconds % 86400
    hours = remainder // 3600
    remainder %= 3600
    minutes = remainder // 60
    seconds = remainder % 60

    parts = []
    if days > 0:
        if days % 7 == 0 and hours == 0 and minutes == 0 and seconds == 0:
            weeks = days // 7
            parts.append(f"{weeks} Minggu" if weeks > 1 else "1 Minggu (7 Hari)")
        else:
            parts.append(f"{days} Hari")
    if hours > 0:
        parts.append(f"{hours} Jam")
    if minutes > 0:
        parts.append(f"{minutes} Menit")
    if seconds > 0 and (days == 0 and hours == 0):
        parts.append(f"{seconds} Detik")
    return " ".join(parts) if parts else f"{total_seconds} Detik"


def format_prize_title(prize: str, winner_count: int = 1) -> str:
    """Format prize title with quantity prefix if appropriate."""
    cleaned = prize.strip()
    if winner_count > 1:
        if not re.match(r"^\d+\s*(?:x\s*|\s+)", cleaned, re.IGNORECASE):
            return f"{winner_count}x {cleaned}"
    return cleaned


def parse_iso_to_unix(iso_str: str) -> int:
    """Convert ISO timestamp string to integer Unix epoch timestamp."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return int(datetime.now(timezone.utc).timestamp())


def build_giveaway_embed(
    giveaway: dict,
    entry_count: int = 0,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    """Build rich interactive embed card for an active giveaway."""
    ends_unix = parse_iso_to_unix(giveaway["ends_at"])
    host_mention = f"<@{giveaway['host_id']}>"
    winner_count = giveaway.get("winner_count", 1)
    
    # Premium Ryukomik Gold & Orange Theme
    is_premium = "premium" in giveaway["prize"].casefold()
    color = discord.Color.from_rgb(255, 140, 0) if is_premium else discord.Color.blurple()

    prize_title = format_prize_title(giveaway["prize"], winner_count)
    winner_desc = f"`{winner_count}` Orang (Masing-masing 1 Hadiah)" if winner_count > 1 else "`1` Orang"

    embed = discord.Embed(
        title=f"🎁 GIVEAWAY: {prize_title}",
        description=(
            f"{giveaway.get('description') or 'Ikuti event giveaway resmi Ryukomik dan dapatkan hadiah menarik!'}\n\n"
            f"🎁 **Hadiah:** **{giveaway['prize']}**\n"
            f"👑 **Jumlah Pemenang:** {winner_desc}\n"
            f"👤 **Host:** {host_mention}\n"
            f"⏳ **Berakhir:** <t:{ends_unix}:R> (<t:{ends_unix}:f>)\n"
            f"👥 **Peserta:** `{entry_count}` Orang"
        ),
        color=color,
    )

    if giveaway.get("requirement_role_id"):
        role_mention = f"<@&{giveaway['requirement_role_id']}>"
        embed.add_field(name="🔒 Syarat Khusus", value=f"Wajib memiliki role {role_mention}", inline=False)

    if is_premium:
        embed.add_field(
            name="✨ Keuntungan Ryukomik Premium",
            value="• Akses semua chapter tanpa jeda / countdown\n• Baca bebas iklan dan fast CDN\n• Badge & Role spesial di website & Discord",
            inline=False,
        )

    embed.set_footer(text=f"Ryukomik Event • ID: #{giveaway['id']} • Klik tombol di bawah untuk ikut!")
    return embed


def build_giveaway_ended_embed(
    giveaway: dict,
    winner_ids: Sequence[int],
    entry_count: int = 0,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    """Build embed card for an ended giveaway."""
    host_mention = f"<@{giveaway['host_id']}>"
    winner_count = giveaway.get("winner_count", 1)
    prize_title = format_prize_title(giveaway["prize"], winner_count)

    if winner_ids:
        winners_str = ", ".join(f"<@{uid}>" for uid in winner_ids)
    else:
        winners_str = "*Tidak ada peserta yang memenuhi syarat.*"

    embed = discord.Embed(
        title=f"🎉 GIVEAWAY BERAKHIR: {prize_title}",
        description=(
            f"Event giveaway ini telah selesai!\n\n"
            f"🎁 **Hadiah:** **{giveaway['prize']}**\n"
            f"👑 **Pemenang ({len(winner_ids)} Orang):** {winners_str}\n"
            f"👤 **Host:** {host_mention}\n"
            f"👥 **Total Peserta:** `{entry_count}` Orang"
        ),
        color=discord.Color.dark_gold(),
    )

    if winner_ids:
        embed.add_field(
            name="📩 Instruksi Klaim Hadiah",
            value=(
                f"Pemenang ({winners_str}) silakan **DM/Chat Admin** ({host_mention}) "
                "dengan menyertakan username akun Ryukomik kamu untuk klaim hadiah!"
            ),
            inline=False,
        )

    embed.set_footer(text=f"Ryukomik Event • ID: #{giveaway['id']} • Giveaway Selesai")
    return embed


def build_winner_announcement(giveaway: dict, winner_ids: Sequence[int]) -> str:
    """Generate public channel announcement mentioning winners with DM admin instructions."""
    winner_count = giveaway.get("winner_count", 1)
    prize_title = format_prize_title(giveaway["prize"], winner_count)

    if not winner_ids:
        return (
            f"📢 **Giveaway #{giveaway['id']} — {prize_title}** telah berakhir, "
            "tetapi tidak ada peserta yang terdaftar. Hadiah dibatalkan."
        )

    winners_mentions = " ".join(f"<@{uid}>" for uid in winner_ids)
    host_mention = f"<@{giveaway['host_id']}>"

    msg = (
        f"🎉 **SELAMAT KEPADA PEMENANG GIVEAWAY!** 🎉\n\n"
        f"🎁 **Hadiah:** **{prize_title}**\n"
        f"👑 **Pemenang ({len(winner_ids)} Orang):** {winners_mentions}\n\n"
        f"📩 **CARA KLAIM HADIAH (PENTING):**\n"
        f"Untuk para pemenang, silakan segera **DM / Chat Admin** ({host_mention} atau Administrator Ryukomik) dengan mengirimkan:\n"
        f"1. Screenshot pesan kemenangan ini\n"
        f"2. Email / Username akun Ryukomik kamu di website (https://ryukomik.my.id)\n\n"
        f"⚡ *Akses Premium Ryukomik akan langsung diaktifkan ke akunmu setelah konfirmasi!* Selamat membaca! 📖✨"
    )
    return msg


def draw_random_winners(
    candidate_ids: Sequence[int],
    count: int,
    guild: discord.Guild | None = None,
) -> list[int]:
    """
    Select `count` random unique winners using cryptographic RNG.
    Filters out users who are no longer members of the guild if guild is provided.
    """
    if not candidate_ids:
        return []

    valid_candidates: list[int] = []
    if guild:
        for uid in candidate_ids:
            if guild.get_member(uid) is not None:
                valid_candidates.append(uid)
    else:
        valid_candidates = list(candidate_ids)

    if not valid_candidates:
        # Fallback to candidates if member cache isn't available
        valid_candidates = list(candidate_ids)

    unique_candidates = list(set(valid_candidates))
    sample_size = min(count, len(unique_candidates))
    if sample_size <= 0:
        return []

    return secrets.SystemRandom().sample(unique_candidates, sample_size)


async def end_giveaway_and_announce(bot: commands.Bot, giveaway: dict) -> tuple[bool, list[int]]:
    """Finalize a giveaway, choose winners, update message, and post announcement."""
    giveaway_id = giveaway["id"]
    channel_id = giveaway["channel_id"]
    message_id = giveaway.get("message_id")
    winner_count = giveaway.get("winner_count", 1)

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            channel = None

    guild = channel.guild if isinstance(channel, discord.TextChannel) else bot.get_guild(giveaway["guild_id"])

    # Retrieve all entries
    candidate_ids = await db.get_giveaway_entries(giveaway_id)
    winner_ids = draw_random_winners(candidate_ids, winner_count, guild)

    # Save to database
    await db.end_giveaway(giveaway_id, winner_ids)

    # Update Discord Message Embed
    if isinstance(channel, discord.TextChannel) and message_id:
        try:
            message = await channel.fetch_message(message_id)
            ended_embed = build_giveaway_ended_embed(giveaway, winner_ids, len(candidate_ids), guild)
            await message.edit(embed=ended_embed, view=None)
        except (discord.NotFound, discord.Forbidden) as error:
            log.warning("Could not edit giveaway message id=%s: %s", message_id, error)

    # Send public winner announcement
    if isinstance(channel, discord.TextChannel):
        announcement_text = build_winner_announcement(giveaway, winner_ids)
        try:
            await channel.send(
                content=announcement_text,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException as error:
            log.warning("Could not send giveaway winner announcement: %s", error)

    return True, winner_ids


async def reroll_giveaway(
    bot: commands.Bot,
    giveaway_id: int,
    count: int = 1,
) -> tuple[bool, str, list[int]]:
    """Reroll new winner(s) for a concluded giveaway."""
    giveaway = await db.get_giveaway(giveaway_id)
    if not giveaway:
        return False, "Giveaway tidak ditemukan.", []

    if giveaway["status"] == "cancelled":
        return False, "Giveaway ini telah dibatalkan dan tidak dapat di-reroll.", []

    channel_id = giveaway["channel_id"]
    message_id = giveaway.get("message_id")
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            channel = None

    guild = channel.guild if isinstance(channel, discord.TextChannel) else bot.get_guild(giveaway["guild_id"])

    candidate_ids = await db.get_giveaway_entries(giveaway_id)
    if not candidate_ids:
        return False, "Tidak ada peserta yang terdaftar dalam giveaway ini.", []

    # Exclude existing winners if possible
    existing_winners = []
    if giveaway.get("winners_json"):
        try:
            existing_winners = json.loads(giveaway["winners_json"])
        except Exception:
            existing_winners = []

    remaining_candidates = [uid for uid in candidate_ids if uid not in existing_winners]
    if not remaining_candidates:
        # If all candidates already won, pool all candidates
        remaining_candidates = candidate_ids

    new_winners = draw_random_winners(remaining_candidates, count, guild)
    if not new_winners:
        return False, "Gagal memilih pemenang baru.", []

    # Update DB
    await db.update_giveaway_winners(giveaway_id, new_winners)

    # Update original message embed if possible
    if isinstance(channel, discord.TextChannel) and message_id:
        try:
            message = await channel.fetch_message(message_id)
            ended_embed = build_giveaway_ended_embed(giveaway, new_winners, len(candidate_ids), guild)
            await message.edit(embed=ended_embed, view=None)
        except Exception:
            pass

    # Send reroll announcement
    if isinstance(channel, discord.TextChannel):
        host_mention = f"<@{giveaway['host_id']}>"
        winners_mentions = " ".join(f"<@{uid}>" for uid in new_winners)
        msg = (
            f"🔄 **REROLL PEMENANG GIVEAWAY #{giveaway['id']}** 🔄\n\n"
            f"🎁 **Hadiah:** **{giveaway['prize']}**\n"
            f"👑 **Pemenang Baru:** {winners_mentions}\n\n"
            f"📩 **CARA KLAIM:**\n"
            f"Pemenang baru silakan segera **DM/Chat Admin** ({host_mention}) dengan menyertakan akun Ryukomik kamu untuk klaim hadiah! 📖✨"
        )
        await channel.send(
            content=msg,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    return True, "Reroll berhasil!", new_winners


async def process_due_giveaways(bot: commands.Bot) -> int:
    """Check and conclude all giveaways that reached their expiration timestamp."""
    due_list = await db.get_due_giveaways()
    processed_count = 0
    for giveaway in due_list:
        try:
            await end_giveaway_and_announce(bot, giveaway)
            processed_count += 1
            log.info("Successfully concluded giveaway id=%s prize=%s", giveaway["id"], giveaway["prize"])
        except Exception as error:
            log.exception("Failed to process due giveaway id=%s: %s", giveaway["id"], error)

    return processed_count

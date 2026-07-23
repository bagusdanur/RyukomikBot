"""Safe, idempotent Discord guild housekeeping.

This module deliberately never creates, moves, renames, or deletes channels.
It only improves content and permissions on channels that already exist.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

import discord

from config import ROLE_ADMIN_ID, ROLE_STAFF_ID, STAFF_TASKS_CHANNEL_ID


log = logging.getLogger(__name__)

WELCOME_NAMES = ("welcome", "selamat-datang", "welcome-goodbye")
RULES_NAMES = ("rules", "peraturan")


def _plain_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _find_text_channel(
    guild: discord.Guild,
    *,
    channel_id: int | None = None,
    names: Iterable[str] = (),
) -> discord.TextChannel | None:
    if channel_id:
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
    wanted = tuple(_plain_name(name) for name in names)
    for channel in guild.text_channels:
        normalized = _plain_name(channel.name)
        if any(name == normalized or name in normalized for name in wanted):
            return channel
    return None


def build_welcome_embed(member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="Selamat Datang di Ryukomik!",
        description=(
            f"Halo {member.mention}, selamat bergabung.\n\n"
            "Mulai dengan membaca **Rules**, pilih role yang sesuai, lalu lihat "
            "informasi series atau rekrutmen yang tersedia."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Langkah pertama",
        value="1. Baca dan patuhi Rules\n2. Ambil role\n3. Gunakan channel sesuai topiknya",
        inline=False,
    )
    embed.add_field(name="Jumlah member", value=f"{member.guild.member_count} anggota", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Ryukomik Community • Selamat membaca dan berkarya")
    return embed


def build_goodbye_embed(member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="Sampai Jumpa",
        description=f"**{discord.utils.escape_markdown(member.display_name)}** telah meninggalkan server.",
        color=discord.Color.dark_grey(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Terima kasih pernah menjadi bagian dari Ryukomik")
    return embed


def build_rules_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Peraturan Komunitas Ryukomik",
        description=(
            "Dengan bergabung dan berinteraksi di server ini, kamu dianggap telah "
            "membaca dan menyetujui peraturan berikut."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="1. Saling menghormati",
        value="Dilarang menghina, melakukan diskriminasi/SARA, melecehkan, atau memancing konflik.",
        inline=False,
    )
    embed.add_field(
        name="2. Spam, promosi, dan keamanan",
        value="Dilarang spam, mention massal, promosi tanpa izin, scam, phishing, atau tautan berbahaya.",
        inline=False,
    )
    embed.add_field(
        name="3. Gunakan channel dengan benar",
        value="Ikuti nama dan topik channel. Konten NSFW atau ilegal tidak diperbolehkan.",
        inline=False,
    )
    embed.add_field(
        name="4. Privasi tiket",
        value="Isi tiket rekrutmen/staff bersifat privat dan tidak boleh disebarkan tanpa izin.",
        inline=False,
    )
    embed.add_field(
        name="5. Moderasi",
        value="Laporkan masalah kepada Administrator. Keputusan moderasi disesuaikan dengan tingkat pelanggaran.",
        inline=False,
    )
    embed.add_field(
        name="6. Ketentuan Discord",
        value="Seluruh anggota wajib mematuhi Discord Terms of Service dan Community Guidelines.",
        inline=False,
    )
    embed.set_footer(text="Ryukomik Official • Peraturan dapat diperbarui bila diperlukan")
    return embed


async def _upsert_bot_embed(
    channel: discord.TextChannel,
    *,
    title: str,
    embed: discord.Embed,
    pin: bool = True,
) -> discord.Message:
    current: discord.Message | None = None
    async for message in channel.history(limit=100):
        if message.author.id != channel.guild.me.id or not message.embeds:
            continue
        if message.embeds[0].title == title:
            current = message
            break
    if current:
        await current.edit(embed=embed)
    else:
        current = await channel.send(embed=embed)
    if pin and not current.pinned:
        await current.pin(reason="Pesan informasi utama Ryukomik")
    return current


async def apply_server_housekeeping(guild: discord.Guild) -> dict[str, bool]:
    """Apply only safe changes to the existing layout."""
    result = {"staff_permissions": False, "rules": False, "topics": False}
    me = guild.me
    if me is None:
        return result

    staff_role = guild.get_role(ROLE_STAFF_ID)
    admin_role = guild.get_role(ROLE_ADMIN_ID)
    if staff_role and staff_role.permissions.mention_everyone:
        permissions = discord.Permissions(staff_role.permissions.value)
        permissions.update(mention_everyone=False)
        await staff_role.edit(
            permissions=permissions,
            reason="Staff tidak memerlukan mention massal",
        )

    tasks_channel = _find_text_channel(guild, channel_id=STAFF_TASKS_CHANNEL_ID)
    if tasks_channel and staff_role and admin_role:
        await tasks_channel.set_permissions(
            guild.default_role,
            view_channel=False,
            reason="Tugas internal hanya untuk staff",
        )
        await tasks_channel.set_permissions(
            staff_role,
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            reason="Staff dapat melihat dan claim tugas",
        )
        await tasks_channel.set_permissions(
            admin_role,
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            reason="Administrator mengelola tugas",
        )
        await tasks_channel.set_permissions(
            me,
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            manage_messages=True,
            reason="Yuki mengelola task card",
        )
        if not tasks_channel.topic:
            await tasks_channel.edit(
                topic="Tugas internal Ryukomik. Staff dapat melihat dan claim tugas yang tersedia.",
                reason="Memperjelas fungsi channel tanpa mengubah layout",
            )
        result["staff_permissions"] = True

    rules_channel = _find_text_channel(guild, names=RULES_NAMES)
    if rules_channel and admin_role:
        await rules_channel.set_permissions(
            guild.default_role,
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            reason="Rules hanya dapat ditulis Administrator",
        )
        await rules_channel.set_permissions(
            admin_role,
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            reason="Administrator mengelola Rules",
        )
        await rules_channel.set_permissions(
            me,
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            manage_messages=True,
            reason="Yuki memperbarui Rules",
        )
        await _upsert_bot_embed(
            rules_channel,
            title="Peraturan Komunitas Ryukomik",
            embed=build_rules_embed(),
        )
        if not rules_channel.topic:
            await rules_channel.edit(
                topic="Baca dan setujui peraturan sebelum berinteraksi di komunitas Ryukomik.",
                reason="Memperjelas fungsi channel tanpa mengubah layout",
            )
        result["rules"] = True

    welcome_channel = _find_text_channel(guild, names=WELCOME_NAMES)
    if welcome_channel and not welcome_channel.topic:
        await welcome_channel.edit(
            topic="Sambutan anggota baru dan informasi langkah pertama di Ryukomik.",
            reason="Memperjelas fungsi channel tanpa mengubah layout",
        )
        result["topics"] = True

    log.info("Server housekeeping completed for guild=%s result=%s", guild.id, result)
    return result


async def send_welcome(member: discord.Member) -> bool:
    channel = _find_text_channel(member.guild, names=WELCOME_NAMES)
    if not channel:
        log.warning("Welcome channel not found in guild=%s", member.guild.id)
        return False
    await channel.send(embed=build_welcome_embed(member))
    return True


async def send_goodbye(member: discord.Member) -> bool:
    channel = _find_text_channel(member.guild, names=WELCOME_NAMES)
    if not channel:
        log.warning("Goodbye channel not found in guild=%s", member.guild.id)
        return False
    await channel.send(embed=build_goodbye_embed(member))
    return True

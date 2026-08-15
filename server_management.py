"""Safe, idempotent Discord guild housekeeping."""

from __future__ import annotations

import logging
import re
from typing import Iterable

import discord

from config import (
    NEW_PROJECT_CHANNEL_ID,
    PROJECT_CATEGORY_ID,
    PROJECT_DROP_CHANNEL_ID,
    ROLE_ADMIN_ID,
    ROLE_STAFF_ID,
    RAW_WATCH_CHANNEL_NAME,
    PROJECT_SCOUT_CHANNEL_NAME,
    STAFF_LOG_CHANNEL_ID,
    STAFF_TASKS_CHANNEL_ID,
    UPDATE_PROJECT_CHANNEL_ID,
)


log = logging.getLogger(__name__)

WELCOME_NAMES = ("welcome", "selamat-datang", "welcome-goodbye")
APPRECIATION_NAMES = ("apresiasi-staff",)
RULES_NAMES = ("rules", "peraturan")
ROLE_NAMES = ("ambil-role", "roles", "pilih-role")
RECRUITMENT_NAMES = ("staff-rekrutmen", "rekrutmen", "recruitment")
WEBSITE_INFO_NAMES = ("info-website", "status-website")
MEMBER_MENTION_PATTERN = re.compile(r"<@!?(\d+)>")

PROJECT_CHANNELS = (
    (NEW_PROJECT_CHANNEL_ID, "・new-project", "Informasi project baru yang akan dikerjakan atau segera hadir di Ryukomik."),
    (UPDATE_PROJECT_CHANNEL_ID, "・update-project", "Pembaruan progres dan status project Ryukomik."),
    (None, "・request-project", "Ajukan judul project yang ingin kamu lihat di Ryukomik. Satu judul per pesan."),
    (PROJECT_DROP_CHANNEL_ID, "・project-drop", "Informasi project yang dihentikan atau tidak dilanjutkan."),
)


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


async def ensure_raw_watch_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """Create one admin-only RAW update channel next to #staff-mod."""
    admin_channel = _find_text_channel(guild, channel_id=STAFF_LOG_CHANNEL_ID)
    if not admin_channel:
        return None
    channel = _find_text_channel(guild, names=(RAW_WATCH_CHANNEL_NAME,))
    if channel is None:
        channel = await guild.create_text_channel(
            RAW_WATCH_CHANNEL_NAME,
            category=admin_channel.category,
            overwrites=dict(admin_channel.overwrites),
            topic="Notifikasi chapter RAW baru untuk project Ryukomik aktif. Admin only.",
            reason="Memisahkan notifikasi RAW Watch dari staff-mod",
        )
    elif channel.name != RAW_WATCH_CHANNEL_NAME:
        await channel.edit(name=RAW_WATCH_CHANNEL_NAME, reason="Menyamakan nama channel RAW Watch")
    try:
        await channel.edit(position=admin_channel.position + 1, reason="Menempatkan RAW Watch di samping staff-mod")
    except discord.HTTPException:
        pass
    return channel


async def ensure_project_scout_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """Create one admin-only channel for automatic revival candidates."""
    admin_channel = _find_text_channel(guild, channel_id=STAFF_LOG_CHANNEL_ID)
    if not admin_channel:
        return None
    channel = _find_text_channel(guild, names=(PROJECT_SCOUT_CHANNEL_NAME,))
    if channel is None:
        channel = await guild.create_text_channel(
            PROJECT_SCOUT_CHANNEL_NAME,
            category=admin_channel.category,
            overwrites=dict(admin_channel.overwrites),
            topic="Kandidat project Indonesia lama yang RAW-nya masih lanjut. Admin only.",
            reason="Membuat channel khusus Auto Revival Scout",
        )
    elif channel.name != PROJECT_SCOUT_CHANNEL_NAME:
        await channel.edit(name=PROJECT_SCOUT_CHANNEL_NAME, reason="Menyamakan nama channel Project Scout")
    try:
        await channel.edit(position=admin_channel.position + 2, reason="Menempatkan Project Scout setelah RAW Watch")
    except discord.HTTPException:
        pass
    return channel


def build_welcome_embed(member: discord.Member) -> discord.Embed:
    display_name = discord.utils.escape_markdown(member.display_name)
    embed = discord.Embed(
        title="Selamat Datang di Ryukomik!",
        description=(
            f"Halo **{display_name}**, selamat bergabung.\n\n"
            "Mulai dengan membaca **Rules**, pilih role yang sesuai, lalu lihat "
            "informasi project atau rekrutmen yang tersedia."
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
    embed.set_footer(text=f"Ryukomik Community • Member baru: {member.display_name}")
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


def build_website_embed() -> discord.Embed:
    """Public directory card for the Ryukomik website."""
    embed = discord.Embed(
        title="Ryukomik Website",
        description=(
            "Pilih layanan Ryukomik yang ingin kamu buka. Semua tautan di bawah "
            "mengarah langsung ke website resmi."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Komik", value="Baca koleksi manga dan manhwa Ryukomik.", inline=False)
    embed.add_field(name="Anime", value="Lihat katalog dan informasi anime.", inline=False)
    embed.add_field(name="Donghua", value="Lihat katalog dan informasi donghua.", inline=False)
    embed.set_footer(text="Ryukomik Official • Bookmark channel ini untuk akses cepat")
    return embed


def build_website_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Buka Komik", emoji="📚", style=discord.ButtonStyle.link, url="https://ryukomik.my.id/"))
    view.add_item(discord.ui.Button(label="Buka Anime", emoji="🎬", style=discord.ButtonStyle.link, url="https://ryukomik.my.id/anime"))
    view.add_item(discord.ui.Button(label="Buka Donghua", emoji="🐉", style=discord.ButtonStyle.link, url="https://ryukomik.my.id/donghua"))
    return view


def build_trakteer_embed() -> discord.Embed:
    embed = discord.Embed(
        title="💜 Dukung Ryukomik di Trakteer",
        description=(
            "Dukunganmu membantu Ryukomik terus menerjemahkan, mengedit, dan merilis project baru. "
            "Setiap dukungan akan tampil otomatis di channel ini. Terima kasih!"
        ),
        color=discord.Color.purple(),
    )
    embed.add_field(name="Cara mendukung", value="Klik tombol **Dukung di Trakteer** di bawah.", inline=False)
    embed.set_footer(text="Ryukomik Official • Dukungan bersifat sukarela")
    return embed


async def upsert_trakteer_card(guild: discord.Guild) -> bool:
    channel = _find_text_channel(guild, names=APPRECIATION_NAMES)
    if not channel:
        log.warning("Appreciation channel not found in guild=%s", guild.id)
        return False
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label="Dukung di Trakteer", emoji="💜", style=discord.ButtonStyle.link,
        url="https://trakteer.id/kanimenia17/tip",
    ))
    message = await _upsert_bot_embed(
        channel, title="💜 Dukung Ryukomik di Trakteer", embed=build_trakteer_embed(), pin=True
    )
    await message.edit(embed=build_trakteer_embed(), view=view)
    return True


def build_welcome_view(guild: discord.Guild) -> discord.ui.View | None:
    """Build channel-link buttons using the existing server layout."""
    targets = (
        ("Baca Rules", "📜", _find_text_channel(guild, names=RULES_NAMES)),
        ("Ambil Role", "🎭", _find_text_channel(guild, names=ROLE_NAMES)),
        ("Info Rekrutmen", "📨", _find_text_channel(guild, names=RECRUITMENT_NAMES)),
    )
    view = discord.ui.View(timeout=None)
    for label, emoji, channel in targets:
        if channel is None:
            continue
        view.add_item(
            discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.link,
                url=f"https://discord.com/channels/{guild.id}/{channel.id}",
            )
        )
    return view if view.children else None


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
    view: discord.ui.View | None = None,
) -> discord.Message:
    current: discord.Message | None = None
    async for message in channel.history(limit=100):
        if message.author.id != channel.guild.me.id or not message.embeds:
            continue
        if message.embeds[0].title == title:
            current = message
            break
    if current:
        await current.edit(embed=embed, view=view)
    else:
        current = await channel.send(embed=embed, view=view)
    if pin and not current.pinned:
        await current.pin(reason="Pesan informasi utama Ryukomik")
    return current


async def _repair_welcome_history(
    channel: discord.TextChannel,
    bot_member: discord.Member,
) -> bool:
    """Replace legacy raw mentions and refresh stored profile thumbnails."""
    changed = False
    async for message in channel.history(limit=100):
        if message.author.id != bot_member.id or not message.embeds:
            continue
        embed = message.embeds[0]
        if embed.title != "Selamat Datang di Ryukomik!" or not embed.description:
            continue
        match = MEMBER_MENTION_PATTERN.search(embed.description)
        if not match:
            continue
        member = channel.guild.get_member(int(match.group(1)))
        replacement = (
            f"**{discord.utils.escape_markdown(member.display_name)}**"
            if member
            else "**Member baru**"
        )
        updated = embed.copy()
        updated.description = MEMBER_MENTION_PATTERN.sub(replacement, embed.description, count=1)
        if member:
            updated.set_thumbnail(url=member.display_avatar.url)
            updated.set_footer(text=f"Ryukomik Community • Member baru: {member.display_name}")
        await message.edit(embed=updated)
        changed = True
    return changed


async def apply_project_layout(guild: discord.Guild) -> bool:
    """Keep the public project category compact and consistently ordered."""
    category = guild.get_channel(PROJECT_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        log.warning("Project category not found: guild=%s id=%s", guild.id, PROJECT_CATEGORY_ID)
        return False

    if category.name != "Info Project":
        await category.edit(name="Info Project", reason="Merombak Info Series menjadi Info Project")

    channels: list[discord.TextChannel] = []
    for channel_id, name, topic in PROJECT_CHANNELS:
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            normalized = _plain_name(name)
            channel = next(
                (
                    item
                    for item in category.text_channels
                    if _plain_name(item.name) == normalized
                ),
                None,
            )
        if channel is None and channel_id is None:
            channel = await guild.create_text_channel(
                name,
                category=category,
                topic=topic,
                reason="Melengkapi pusat informasi project",
            )
        if not isinstance(channel, discord.TextChannel):
            log.warning("Project channel missing: guild=%s id=%s name=%s", guild.id, channel_id, name)
            return False

        changes = {}
        if channel.name != name:
            changes["name"] = name
        if channel.topic != topic:
            changes["topic"] = topic
        if channel.category_id != category.id:
            changes["category"] = category
            changes["sync_permissions"] = False
        if changes:
            await channel.edit(reason="Merapikan layout Info Project", **changes)
        channels.append(channel)

    current_ids = [channel.id for channel in category.text_channels]
    desired_ids = [channel.id for channel in channels]
    if [channel_id for channel_id in current_ids if channel_id in desired_ids] != desired_ids:
        await channels[0].move(beginning=True, reason="Mengurutkan channel Info Project")
        for previous, channel in zip(channels, channels[1:]):
            await channel.move(after=previous, reason="Mengurutkan channel Info Project")

    return True


async def apply_server_housekeeping(guild: discord.Guild) -> dict[str, bool]:
    """Apply only safe changes to the existing layout."""
    result = {
        "project_layout": False,
        "staff_permissions": False,
        "rules": False,
        "topics": False,
        "review_cleanup": False,
        "welcome_history": False,
        "raw_watch": False,
        "project_scout": False,
        "website_info": False,
    }
    print(f"[SERVER] Starting safe housekeeping for {guild.name}", flush=True)
    me = guild.me
    if me is None:
        return result

    result["raw_watch"] = bool(await ensure_raw_watch_channel(guild))
    result["project_scout"] = bool(await ensure_project_scout_channel(guild))

    result["project_layout"] = await apply_project_layout(guild)

    staff_role = guild.get_role(ROLE_STAFF_ID)
    admin_role = guild.get_role(ROLE_ADMIN_ID)
    if staff_role and staff_role.permissions.mention_everyone:
        permissions = discord.Permissions(staff_role.permissions.value)
        permissions.update(mention_everyone=False)
        await staff_role.edit(
            permissions=permissions,
            reason="Staff tidak memerlukan mention massal",
        )
        print("[SERVER] Staff mass-mention permission disabled", flush=True)

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
        print("[SERVER] staff-tasks permissions and topic checked", flush=True)

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
        print("[SERVER] Rules permissions, content, and pin checked", flush=True)

    website_channel = _find_text_channel(guild, names=WEBSITE_INFO_NAMES)
    if website_channel:
        changes = {}
        if website_channel.name != "・info-website":
            changes["name"] = "・info-website"
        website_topic = "Tautan resmi Ryukomik: Komik, Anime, dan Donghua."
        if website_channel.topic != website_topic:
            changes["topic"] = website_topic
        if changes:
            await website_channel.edit(reason="Mengganti Status Website menjadi Info Website", **changes)
        await _upsert_bot_embed(
            website_channel,
            title="Ryukomik Website",
            embed=build_website_embed(),
            view=build_website_view(),
        )
        result["website_info"] = True

    welcome_channel = _find_text_channel(guild, names=WELCOME_NAMES)
    if welcome_channel:
        if not welcome_channel.topic:
            await welcome_channel.edit(
                topic="Sambutan anggota baru dan informasi langkah pertama di Ryukomik.",
                reason="Memperjelas fungsi channel tanpa mengubah layout",
            )
            result["topics"] = True
        result["welcome_history"] = await _repair_welcome_history(welcome_channel, me)

    admin_channel = _find_text_channel(guild, channel_id=STAFF_LOG_CHANNEL_ID)
    if admin_channel:
        async for message in admin_channel.history(limit=200):
            if message.author.id != me.id:
                continue
            is_claim_noise = " claim tugas " in (message.content or "").casefold()
            title = message.embeds[0].title if message.embeds else None
            is_stale_review_notice = title in {
                "Perlu Revisi",
                "Tugas Disetujui",
                "⏳ Hasil Belum Direview",
            }
            if is_claim_noise or is_stale_review_notice:
                await message.delete()
        result["review_cleanup"] = True

    result["trakteer"] = await upsert_trakteer_card(guild)

    log.info("Server housekeeping completed for guild=%s result=%s", guild.id, result)
    print(f"[SERVER] Housekeeping result: {result}", flush=True)
    return result


async def send_welcome(member: discord.Member) -> bool:
    channel = _find_text_channel(member.guild, names=WELCOME_NAMES)
    if not channel:
        log.warning("Welcome channel not found in guild=%s", member.guild.id)
        return False
    await channel.send(
        content=f"Selamat datang, {member.mention}! 👋",
        embed=build_welcome_embed(member),
        view=build_welcome_view(member.guild),
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )
    return True


async def send_goodbye(member: discord.Member) -> bool:
    channel = _find_text_channel(member.guild, names=WELCOME_NAMES)
    if not channel:
        log.warning("Goodbye channel not found in guild=%s", member.guild.id)
        return False
    await channel.send(embed=build_goodbye_embed(member))
    return True

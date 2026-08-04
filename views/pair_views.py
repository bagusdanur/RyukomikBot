"""Persistent Discord controls for collaborative TL/TS projects."""

import logging
import re

import discord

import pair_workflow as pairs
from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import find_ticket, format_currency, is_admin
from raw_downloader import get_downloader
from raw_downloader.resolver import SOURCE_ORDER, resolve_assignment_raw
from views.raw_views import RawChapterView, RawSearchView

logger = logging.getLogger(__name__)
DRIVE_PREFIXES = ("https://drive.google.com/", "http://drive.google.com/")
STATE_LABELS = {
    "waiting_tl": "Menunggu TL",
    "ready_for_ts": "Siap TS",
    "tl_revision": "Perbaikan TL",
    "ts_revision": "Perbaikan TS",
    "both_revision": "Perbaikan TL + TS",
    "final_review": "Review Final",
    "completed": "Selesai",
}
NEXT_ACTION = {
    "waiting_tl": "TL mengirim hasil terjemahan",
    "tl_revision": "TL memperbaiki terjemahan",
    "both_revision": "TL dan TS memperbaiki hasil",
    "ready_for_ts": "TS mengerjakan hasil final",
    "ts_revision": "TS memperbaiki hasil final",
    "final_review": "Administrator melakukan review final",
    "completed": "Tidak ada — chapter selesai",
}


def build_project_embed(project: dict) -> discord.Embed:
    completed = sum(item["status"] == "completed" for item in project["chapters"])
    embed = discord.Embed(
        title=f"Kolaborasi TL–TS • {project['manga']}",
        description=(
            f"<@{project['tl_staff_id']}> sebagai **Translator** dan "
            f"<@{project['ts_staff_id']}> sebagai **Typesetter** bekerja dalam satu ruang.\n"
            "Gaji setiap chapter dilepas untuk keduanya setelah hasil final disetujui Administrator."
        ),
        color=discord.Color.blurple(),
    )
    progress = []
    for item in project["chapters"]:
        icon = "✅" if item["status"] == "completed" else "🔄" if "revision" in item["status"] else "•"
        progress.append(f"{icon} **Chapter {item['chapter']}** — {STATE_LABELS.get(item['status'], item['status'])}")
    embed.add_field(name=f"Progress ({completed}/{len(project['chapters'])})", value="\n".join(progress), inline=False)
    embed.add_field(name="Rate TL", value=format_currency(int(project["tl_rate_per_chapter"])), inline=True)
    embed.add_field(name="Rate TS", value=format_currency(int(project["ts_rate_per_chapter"])), inline=True)
    embed.add_field(name="Deadline", value=project.get("deadline_at") or "Tidak ditentukan", inline=True)
    embed.set_footer(text=f"Pair Project #{project['id']} • Gunakan tombol sesuai peran")
    return embed


async def refresh_project_panel(guild: discord.Guild, project_id: int) -> None:
    project = await pairs.get_project(project_id)
    if not project or not project.get("channel_id") or not project.get("panel_message_id"):
        return
    channel = guild.get_channel(int(project["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(int(project["panel_message_id"]))
        await message.edit(embed=build_project_embed(project), view=PairProjectView(project_id))
    except discord.HTTPException:
        logger.exception("Failed to refresh pair project panel %s", project_id)


async def _notify_member_ticket(guild: discord.Guild, member_id: int, embed: discord.Embed) -> bool:
    ticket = await find_ticket(guild, member_id)
    member = guild.get_member(member_id)
    if not ticket:
        return False
    await ticket.send(content=member.mention if member else f"<@{member_id}>", embed=embed)
    return True


async def publish_final_review(guild: discord.Guild, chapter_id: int) -> None:
    chapter = await pairs.get_chapter(chapter_id)
    if not chapter:
        return
    channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("Channel staff-mod tidak ditemukan.")
    embed = discord.Embed(
        title=f"Review Final Pair • {chapter['manga']} Chapter {chapter['chapter']}",
        description="TL dan TS telah menyelesaikan chapter ini. Satu persetujuan akan melepas kedua gaji.",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Translator", value=f"<@{chapter['tl_staff_id']}> • {format_currency(chapter['tl_rate_per_chapter'])}", inline=True)
    embed.add_field(name="Typesetter", value=f"<@{chapter['ts_staff_id']}> • {format_currency(chapter['ts_rate_per_chapter'])}", inline=True)
    embed.add_field(name="Ruang Proyek", value=f"<#{chapter['channel_id']}>", inline=False)
    embed.add_field(name="Hasil TL", value=chapter.get("tl_link") or "Tidak tersedia", inline=False)
    embed.add_field(name="Hasil Final", value=chapter.get("final_link") or "Tidak tersedia", inline=False)
    if chapter.get("notes"):
        embed.add_field(name="Catatan", value=chapter["notes"], inline=False)
    embed.set_footer(text=f"Pair Chapter #{chapter_id} • Review Administrator")
    message = None
    if chapter.get("review_message_id"):
        try:
            message = await channel.fetch_message(int(chapter["review_message_id"]))
            await message.edit(embed=embed, view=PairAdminReviewView(chapter_id))
        except discord.HTTPException:
            message = None
    if message is None:
        message = await channel.send(embed=embed, view=PairAdminReviewView(chapter_id))
    await pairs.set_review_message(chapter_id, message.id)


async def remove_final_review(guild: discord.Guild, chapter: dict) -> None:
    if not chapter.get("review_message_id"):
        return
    channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        try:
            message = await channel.fetch_message(int(chapter["review_message_id"]))
            await message.delete()
        except discord.HTTPException:
            pass
    await pairs.set_review_message(int(chapter["id"]), None)


def build_ts_handoff_embed(chapter: dict, *, completed: bool = False) -> discord.Embed:
    embed = discord.Embed(
        title=(
            f"Hasil Final TS Dikirim • {chapter['manga']} Chapter {chapter['chapter']}"
            if completed else f"Siap Dikerjakan TS • {chapter['manga']} Chapter {chapter['chapter']}"
        ),
        description=(
            "Hasil final sudah dikirim dan sekarang menunggu review Administrator."
            if completed else
            f"<@{chapter['ts_staff_id']}>, hasil terjemahan TL sudah tersedia. "
            "Silakan kerjakan typesetting, lalu kirim hasil final melalui tombol di bawah."
        ),
        color=discord.Color.green() if completed else discord.Color.blurple(),
    )
    embed.add_field(name="Translator", value=f"<@{chapter['tl_staff_id']}>", inline=True)
    embed.add_field(name="Typesetter", value=f"<@{chapter['ts_staff_id']}>", inline=True)
    embed.add_field(name="Chapter", value=str(chapter["chapter"]), inline=True)
    embed.add_field(name="Hasil TL", value=f"[Buka Google Drive]({chapter['tl_link']})", inline=False)
    if completed and chapter.get("final_link"):
        embed.add_field(name="Hasil Final TS", value=f"[Buka Google Drive]({chapter['final_link']})", inline=False)
    if chapter.get("notes"):
        embed.add_field(
            name="Catatan Terakhir" if completed else "Catatan TL",
            value=str(chapter["notes"])[:1024], inline=False,
        )
    embed.set_footer(text=f"Pair Chapter #{chapter['id']} • Handoff TL ke TS")
    return embed


async def publish_ts_handoff(guild: discord.Guild, chapter_id: int, *, completed: bool = False) -> None:
    chapter = await pairs.get_chapter(chapter_id)
    if not chapter or not chapter.get("channel_id") or not chapter.get("tl_link"):
        return
    channel = guild.get_channel(int(chapter["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return
    message = None
    if chapter.get("ts_handoff_message_id"):
        try:
            message = await channel.fetch_message(int(chapter["ts_handoff_message_id"]))
            await message.edit(
                content=None if completed else f"<@{chapter['ts_staff_id']}>",
                embed=build_ts_handoff_embed(chapter, completed=completed),
                view=None if completed else PairTsHandoffView(chapter_id),
            )
        except discord.HTTPException:
            message = None
    if message is None:
        message = await channel.send(
            content=None if completed else f"<@{chapter['ts_staff_id']}>",
            embed=build_ts_handoff_embed(chapter, completed=completed),
            view=None if completed else PairTsHandoffView(chapter_id),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await pairs.set_ts_handoff_message(chapter_id, message.id)


class PairLinkModal(discord.ui.Modal):
    link = discord.ui.TextInput(label="Link Google Drive", placeholder="https://drive.google.com/...", required=True)
    notes = discord.ui.TextInput(label="Catatan (Opsional)", style=discord.TextStyle.paragraph, required=False, max_length=1000)

    def __init__(self, chapter_id: int, action: str):
        super().__init__(title="Submit Hasil TL" if action == "tl" else "Submit Hasil Final TS")
        self.chapter_id, self.action = chapter_id, action

    async def on_submit(self, interaction: discord.Interaction):
        link = self.link.value.strip()
        if not link.startswith(DRIVE_PREFIXES):
            return await interaction.response.send_message("Masukkan link Google Drive yang valid.", ephemeral=True)
        handler = pairs.submit_tl if self.action == "tl" else pairs.submit_final
        if not await handler(self.chapter_id, interaction.user.id, link, self.notes.value or None):
            return await interaction.response.send_message("Aksi tidak tersedia untuk peran atau status chapter saat ini.", ephemeral=True)
        chapter = await pairs.get_chapter(self.chapter_id)
        await interaction.response.send_message(
            "Hasil TL diterima dan chapter sekarang siap untuk TS."
            if self.action == "tl" else "Hasil final dikirim ke Administrator untuk review.",
            ephemeral=False,
        )
        if interaction.guild and chapter:
            await refresh_project_panel(interaction.guild, int(chapter["project_id"]))
            if self.action == "tl":
                await publish_ts_handoff(interaction.guild, self.chapter_id)
            else:
                await publish_ts_handoff(interaction.guild, self.chapter_id, completed=True)
                await publish_final_review(interaction.guild, self.chapter_id)


class PairRevisionModal(discord.ui.Modal, title="Catatan Perbaikan"):
    notes = discord.ui.TextInput(label="Bagian yang harus diperbaiki", style=discord.TextStyle.paragraph, required=True, max_length=1500)

    def __init__(self, chapter_id: int, target: str, admin: bool):
        super().__init__()
        self.chapter_id, self.target, self.admin = chapter_id, target, admin

    async def on_submit(self, interaction: discord.Interaction):
        if self.admin and not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya Administrator yang dapat melakukan aksi ini.", ephemeral=True)
        before = await pairs.get_chapter(self.chapter_id)
        if not await pairs.request_revision(
            self.chapter_id, interaction.user.id, self.target, self.notes.value.strip(), admin=self.admin
        ):
            return await interaction.response.send_message("Revisi gagal karena peran atau status chapter telah berubah.", ephemeral=True)
        chapter = await pairs.get_chapter(self.chapter_id)
        await interaction.response.send_message(
            f"Permintaan perbaikan **{self.target.upper()}** disimpan dan terlihat di ruang proyek.", ephemeral=False
        )
        if interaction.guild and chapter:
            await refresh_project_panel(interaction.guild, int(chapter["project_id"]))
            if before and before.get("status") == "final_review":
                await remove_final_review(interaction.guild, before)
            for member_id in ({int(chapter["tl_staff_id"])} if self.target == "tl" else
                              {int(chapter["ts_staff_id"])} if self.target == "ts" else
                              {int(chapter["tl_staff_id"]), int(chapter["ts_staff_id"])}):
                embed = discord.Embed(
                    title=f"Perbaikan Pair • Chapter {chapter['chapter']}",
                    description=self.notes.value.strip(), color=discord.Color.orange(),
                )
                embed.add_field(name="Ruang Proyek", value=f"<#{chapter['channel_id']}>")
                await _notify_member_ticket(interaction.guild, member_id, embed)


class PairChapterSelect(discord.ui.Select):
    def __init__(self, project: dict, action: str):
        allowed = {
            "tl": {"waiting_tl", "tl_revision", "both_revision"},
            "final": {"ready_for_ts", "ts_revision"},
            "request_tl": {"ready_for_ts", "ts_revision", "final_review"},
        }[action]
        rows = [item for item in project["chapters"] if item["status"] in allowed]
        options = [
            discord.SelectOption(label=f"Chapter {item['chapter']}", value=str(item["id"]),
                                  description=STATE_LABELS.get(item["status"], item["status"]))
            for item in rows
        ]
        super().__init__(placeholder="Pilih chapter...", options=options[:25])
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        chapter_id = int(self.values[0])
        if self.action in {"tl", "final"}:
            await interaction.response.send_modal(PairLinkModal(chapter_id, self.action))
        else:
            await interaction.response.send_modal(PairRevisionModal(chapter_id, "tl", False))


class PairChapterSelectView(discord.ui.View):
    def __init__(self, project: dict, action: str):
        super().__init__(timeout=180)
        self.add_item(PairChapterSelect(project, action))


async def open_project_action(interaction: discord.Interaction, project_id: int, action: str):
    project = await pairs.get_project(project_id)
    if not project:
        return await interaction.response.send_message("Proyek pair tidak ditemukan.", ephemeral=True)
    expected = int(project["tl_staff_id"] if action == "tl" else project["ts_staff_id"])
    if interaction.user.id != expected and not is_admin(interaction.user):
        return await interaction.response.send_message("Tombol ini hanya untuk staff yang ditugaskan.", ephemeral=True)
    allowed = {
        "tl": {"waiting_tl", "tl_revision", "both_revision"},
        "final": {"ready_for_ts", "ts_revision"},
        "request_tl": {"ready_for_ts", "ts_revision", "final_review"},
    }[action]
    if not any(item["status"] in allowed for item in project["chapters"]):
        return await interaction.response.send_message("Tidak ada chapter yang dapat diproses untuk aksi ini.", ephemeral=True)
    await interaction.response.send_message("Pilih chapter yang ingin diproses.", view=PairChapterSelectView(project, action), ephemeral=True)


async def show_project_status(interaction: discord.Interaction, project_id: int):
    project = await pairs.get_project(project_id)
    if not project:
        return await interaction.response.send_message("Proyek pair tidak ditemukan.", ephemeral=True)
    participants = {int(project["tl_staff_id"]), int(project["ts_staff_id"])}
    if interaction.user.id not in participants and not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Status detail hanya dapat dilihat oleh TL, TS, dan Administrator proyek.", ephemeral=True
        )
    events = await pairs.timeline(project_id)
    embed = discord.Embed(
        title=f"Status Chapter • {project['manga']}",
        description=(
            f"**TL:** <@{project['tl_staff_id']}> • **TS:** <@{project['ts_staff_id']}>\n"
            "Gunakan bagian *Tindakan berikutnya* untuk mengetahui siapa yang perlu bergerak."
        ),
        color=discord.Color.blurple(),
    )
    for chapter in project["chapters"][:5]:
        details = [
            f"**Status:** {STATE_LABELS.get(chapter['status'], chapter['status'])}",
            f"**Tindakan berikutnya:** {NEXT_ACTION.get(chapter['status'], 'Periksa bersama Administrator')}",
        ]
        if chapter.get("tl_link"):
            details.append(f"[Buka hasil TL]({chapter['tl_link']})")
        if chapter.get("final_link"):
            details.append(f"[Buka hasil final]({chapter['final_link']})")
        embed.add_field(
            name=f"Chapter {chapter['chapter']}", value="\n".join(details), inline=False
        )
    revision_events = [event for event in events if str(event["event_type"]).startswith("revision_")][:5]
    if revision_events:
        history = []
        for event in revision_events:
            detail = str(event.get("detail") or "Tanpa catatan").replace("\n", " ")
            if len(detail) > 160:
                detail = detail[:157] + "..."
            actor = f"<@{event['actor_id']}>" if event.get("actor_id") else "Sistem"
            history.append(f"• {event['created_at'][:16]} • {actor}: {detail}")
        embed.add_field(name="Riwayat Revisi Terbaru", value="\n".join(history), inline=False)
    else:
        embed.add_field(name="Riwayat Revisi", value="Belum ada permintaan revisi.", inline=False)
    embed.set_footer(text=f"Pair Project #{project_id} • Tampilan privat")
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def open_project_raw(interaction: discord.Interaction, project_id: int):
    project = await pairs.get_project(project_id)
    if not project:
        return await interaction.response.send_message("Proyek pair tidak ditemukan.", ephemeral=True)
    participants = {int(project["tl_staff_id"]), int(project["ts_staff_id"])}
    if interaction.user.id not in participants and not is_admin(interaction.user):
        return await interaction.response.send_message("RAW ini hanya untuk TL, TS, dan Administrator proyek.", ephemeral=True)
    allowed = [str(item["chapter"]) for item in project["chapters"]]
    await interaction.response.defer(ephemeral=True, thinking=True)

    async def progress(message: str):
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="Mendeteksi RAW Proyek…",
                description=f"**{project['manga']}**\nChapter tugas: **{', '.join(allowed)}**\n\n{message}",
                color=discord.Color.gold(),
            ),
            view=None,
        )

    result = await resolve_assignment_raw(
        project["manga"], allowed,
        {source: get_downloader(source) for source in SOURCE_ORDER},
        progress=progress,
    )
    if result["status"] == "resolved":
        source = result["source"]
        return await interaction.edit_original_response(
            embed=discord.Embed(
                title="RAW Pair Ditemukan",
                description=(
                    f"**{result['manga'].get('title')}** • **{source.title()}**\n"
                    f"Pilih atau download seluruh chapter batch: **{', '.join(allowed)}**."
                ),
                color=discord.Color.green(),
            ),
            view=RawChapterView(
                source, str(result["manga"]["id"]), result["chapters"], restricted=True,
                fallbacks=[{"source": item["source"], "manga_id": str(item["manga"]["id"])} for item in result.get("fallbacks", [])],
            ),
        )
    if result["status"] == "ambiguous":
        return await interaction.edit_original_response(
            embed=discord.Embed(title="Pilih Judul RAW", description="Ada beberapa judul mirip. Pilih manga yang benar.", color=discord.Color.blue()),
            view=RawSearchView("auto", result["combined"], allowed_chapters=allowed),
        )
    messages = {
        "timeout": "API RAW belum merespons dalam batas waktu. Bot sudah mencoba ulang otomatis.",
        "chapters_missing": f"Judul ditemukan, tetapi chapter **{', '.join(allowed)}** belum tersedia.",
        "not_found": f"RAW untuk **{project['manga']}** belum ditemukan di seluruh sumber.",
    }
    await interaction.edit_original_response(
        embed=discord.Embed(title="RAW Belum Tersedia", description=messages.get(result["status"], "Pencarian RAW gagal."), color=discord.Color.orange()),
        view=None,
    )


class PairTlDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"pair:tl:(?P<project_id>\d+):v2"):
    def __init__(self, project_id: int):
        self.project_id = project_id
        super().__init__(discord.ui.Button(label="Submit Hasil TL", style=discord.ButtonStyle.primary, custom_id=f"pair:tl:{project_id}:v2"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["project_id"]))
    async def callback(self, interaction): await open_project_action(interaction, self.project_id, "tl")


class PairTsDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"pair:ts:(?P<project_id>\d+):v2"):
    def __init__(self, project_id: int):
        self.project_id = project_id
        super().__init__(discord.ui.Button(label="Submit Final TS", style=discord.ButtonStyle.success, custom_id=f"pair:ts:{project_id}:v2"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["project_id"]))
    async def callback(self, interaction): await open_project_action(interaction, self.project_id, "final")


class PairTsChapterDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"pair:ts-chapter:(?P<chapter_id>\d+):v2"):
    def __init__(self, chapter_id: int):
        self.chapter_id = chapter_id
        super().__init__(discord.ui.Button(
            label="Submit Hasil Final TS", style=discord.ButtonStyle.success,
            custom_id=f"pair:ts-chapter:{chapter_id}:v2",
        ))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["chapter_id"]))
    async def callback(self, interaction: discord.Interaction):
        chapter = await pairs.get_chapter(self.chapter_id)
        if not chapter:
            return await interaction.response.send_message("Chapter pair tidak ditemukan.", ephemeral=True)
        if interaction.user.id != int(chapter["ts_staff_id"]) and not is_admin(interaction.user):
            return await interaction.response.send_message("Tombol ini hanya untuk TS yang ditugaskan.", ephemeral=True)
        if chapter["status"] not in {"ready_for_ts", "ts_revision"}:
            return await interaction.response.send_message("Chapter ini tidak sedang menunggu hasil TS.", ephemeral=True)
        await interaction.response.send_modal(PairLinkModal(self.chapter_id, "final"))


class PairTlRevisionChapterDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"pair:tl-revision-chapter:(?P<chapter_id>\d+):v2"):
    def __init__(self, chapter_id: int):
        self.chapter_id = chapter_id
        super().__init__(discord.ui.Button(
            label="Minta Perbaikan TL", style=discord.ButtonStyle.danger,
            custom_id=f"pair:tl-revision-chapter:{chapter_id}:v2",
        ))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["chapter_id"]))
    async def callback(self, interaction: discord.Interaction):
        chapter = await pairs.get_chapter(self.chapter_id)
        if not chapter:
            return await interaction.response.send_message("Chapter pair tidak ditemukan.", ephemeral=True)
        if interaction.user.id != int(chapter["ts_staff_id"]) and not is_admin(interaction.user):
            return await interaction.response.send_message("Tombol ini hanya untuk TS yang ditugaskan.", ephemeral=True)
        await interaction.response.send_modal(PairRevisionModal(self.chapter_id, "tl", False))


class PairTlRevisionDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"pair:tl-revision:(?P<project_id>\d+):v2"):
    def __init__(self, project_id: int):
        self.project_id = project_id
        super().__init__(discord.ui.Button(label="Minta Perbaikan TL", style=discord.ButtonStyle.danger, custom_id=f"pair:tl-revision:{project_id}:v2"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["project_id"]))
    async def callback(self, interaction): await open_project_action(interaction, self.project_id, "request_tl")


class PairStatusDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"pair:status:(?P<project_id>\d+):v2"):
    def __init__(self, project_id: int):
        self.project_id = project_id
        super().__init__(discord.ui.Button(
            label="Lihat Status Chapter", style=discord.ButtonStyle.secondary,
            custom_id=f"pair:status:{project_id}:v2",
        ))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["project_id"]))
    async def callback(self, interaction): await show_project_status(interaction, self.project_id)


class PairRawDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"pair:raw:(?P<project_id>\d+):v2"):
    def __init__(self, project_id: int):
        self.project_id = project_id
        super().__init__(discord.ui.Button(
            label="Download RAW", style=discord.ButtonStyle.secondary,
            custom_id=f"pair:raw:{project_id}:v2",
        ))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["project_id"]))
    async def callback(self, interaction): await open_project_raw(interaction, self.project_id)


class PairApproveDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"pair:approve:(?P<chapter_id>\d+):v2"):
    def __init__(self, chapter_id: int):
        self.chapter_id = chapter_id
        super().__init__(discord.ui.Button(label="Setujui Final", style=discord.ButtonStyle.success, custom_id=f"pair:approve:{chapter_id}:v2"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["chapter_id"]))
    async def callback(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya Administrator yang dapat menyetujui hasil final.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        chapter = await pairs.approve_final(self.chapter_id, interaction.user.id)
        if not chapter:
            return await interaction.followup.send("Chapter sudah diproses atau statusnya berubah.", ephemeral=True)
        if interaction.message:
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.title = f"✅ Pair Selesai • {chapter['manga']} Chapter {chapter['chapter']}"
            embed.description = "Hasil final disetujui. Gaji TL dan TS masuk ke saldo secara bersamaan."
            embed.color = discord.Color.green()
            await interaction.message.edit(embed=embed, view=None)
        await refresh_project_panel(interaction.guild, int(chapter["project_id"]))
        for member_id, role, rate in (
            (int(chapter["tl_staff_id"]), "TL", int(chapter["tl_rate_per_chapter"])),
            (int(chapter["ts_staff_id"]), "TS", int(chapter["ts_rate_per_chapter"])),
        ):
            embed = discord.Embed(
                title="✅ Chapter Pair Selesai",
                description="Hasil final disetujui Administrator dan bayaran masuk ke saldo.",
                color=discord.Color.green(),
            )
            embed.add_field(name="Manga", value=chapter["manga"], inline=False)
            embed.add_field(name="Chapter", value=chapter["chapter"], inline=True)
            embed.add_field(name="Role", value=role, inline=True)
            embed.add_field(name="Bayaran", value=format_currency(rate), inline=True)
            embed.add_field(name="Hasil Final", value=chapter.get("final_link") or "Tidak tersedia", inline=False)
            await _notify_member_ticket(interaction.guild, member_id, embed)
        await interaction.followup.send("Final disetujui; gaji TL dan TS dilepas bersamaan.", ephemeral=True)


class PairRevisionTargetSelect(discord.ui.Select):
    def __init__(self, chapter_id: int):
        super().__init__(placeholder="Pilih pihak yang harus memperbaiki", options=[
            discord.SelectOption(label="Revisi TL", value="tl"),
            discord.SelectOption(label="Revisi TS", value="ts"),
            discord.SelectOption(label="Revisi Keduanya", value="both"),
        ])
        self.chapter_id = chapter_id
    async def callback(self, interaction):
        await interaction.response.send_modal(PairRevisionModal(self.chapter_id, self.values[0], True))


class PairRevisionTargetView(discord.ui.View):
    def __init__(self, chapter_id: int):
        super().__init__(timeout=180)
        self.add_item(PairRevisionTargetSelect(chapter_id))


class PairReviseDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"pair:revise:(?P<chapter_id>\d+):v2"):
    def __init__(self, chapter_id: int):
        self.chapter_id = chapter_id
        super().__init__(discord.ui.Button(label="Revisi", style=discord.ButtonStyle.danger, custom_id=f"pair:revise:{chapter_id}:v2"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["chapter_id"]))
    async def callback(self, interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya Administrator yang dapat melakukan review.", ephemeral=True)
        await interaction.response.send_message("Pilih target revisi.", view=PairRevisionTargetView(self.chapter_id), ephemeral=True)


class PairProjectView(discord.ui.View):
    def __init__(self, project_id: int):
        super().__init__(timeout=None)
        self.add_item(PairTlDynamic(project_id))
        self.add_item(PairTsDynamic(project_id))
        self.add_item(PairTlRevisionDynamic(project_id))
        self.add_item(PairStatusDynamic(project_id))
        self.add_item(PairRawDynamic(project_id))


class PairTsHandoffView(discord.ui.View):
    def __init__(self, chapter_id: int):
        super().__init__(timeout=None)
        self.add_item(PairTsChapterDynamic(chapter_id))
        self.add_item(PairTlRevisionChapterDynamic(chapter_id))


class PairAdminReviewView(discord.ui.View):
    def __init__(self, chapter_id: int):
        super().__init__(timeout=None)
        self.add_item(PairApproveDynamic(chapter_id))
        self.add_item(PairReviseDynamic(chapter_id))

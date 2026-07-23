import logging
import re

import discord

import database as db
from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import is_admin, is_staff

logger = logging.getLogger(__name__)
TASK_ID_PATTERN = re.compile(r"#(\d+)")


def task_id_from_message(message: discord.Message | None) -> int | None:
    """Recover an assignment id from a legacy task/review message."""
    if not message:
        return None
    candidates = [message.content]
    for embed in message.embeds:
        candidates.extend([embed.title or "", embed.description or "", embed.footer.text or ""])
    for value in candidates:
        match = TASK_ID_PATTERN.search(value or "")
        if match:
            return int(match.group(1))
    return None


async def _validated_assignment(interaction: discord.Interaction, assignment_id: int, statuses: tuple[str, ...], admin=False):
    assignment = await db.get_assignment(assignment_id)
    if not assignment:
        await interaction.response.send_message("Tugas tidak ditemukan atau sudah dihapus.", ephemeral=True)
        return None
    if assignment["status"] not in statuses:
        await interaction.response.send_message(
            f"Aksi tidak tersedia karena status tugas sekarang **{assignment['status']}**.", ephemeral=True
        )
        return None
    if admin:
        if not is_admin(interaction.user):
            await interaction.response.send_message("Hanya administrator yang dapat melakukan aksi ini.", ephemeral=True)
            return None
    elif not is_staff(interaction.user) or int(assignment["staff_id"] or 0) != interaction.user.id:
        await interaction.response.send_message("Kamu hanya dapat mengirim tugas milikmu sendiri.", ephemeral=True)
        return None
    return assignment


async def _notify_ticket(interaction: discord.Interaction, assignment: dict, embed: discord.Embed):
    channel_id = assignment.get("ticket_channel_id")
    channel = interaction.guild.get_channel(channel_id) if interaction.guild and channel_id else None
    if interaction.guild and not isinstance(channel, discord.TextChannel):
        from helpers.utils import find_ticket

        channel = await find_ticket(interaction.guild, int(assignment["staff_id"]))
        if isinstance(channel, discord.TextChannel):
            await db.set_assignment_ticket_channel(int(assignment["id"]), channel.id)
    if isinstance(channel, discord.TextChannel):
        staff = interaction.guild.get_member(int(assignment["staff_id"]))
        await channel.send(content=staff.mention if staff else None, embed=embed)
        return True
    logger.error(
        "Private ticket not found for assignment=%s staff=%s",
        assignment.get("id"),
        assignment.get("staff_id"),
    )
    return False


def build_completed_embed(assignment: dict) -> discord.Embed:
    """Build the final report delivered to the staff's private ticket."""
    chapter_count = int(assignment.get("chapter_count") or 1)
    total = int(assignment.get("final_rate") or 0)
    rate = int(assignment.get("rate_per_chapter") or (total // chapter_count if chapter_count else total))
    embed = discord.Embed(
        title="✅ Tugas Selesai",
        description=(
            "Hasil kerja telah diperiksa dan **disetujui Administrator**. "
            "Bayaran sudah masuk ke rekap gaji."
        ),
        color=discord.Color.green(),
    )
    embed.add_field(name="Manga", value=assignment["manga"], inline=False)
    embed.add_field(name="Chapter", value=assignment["chapter"], inline=True)
    embed.add_field(name="Role", value=assignment["role"], inline=True)
    embed.add_field(name="Jumlah Chapter", value=str(chapter_count), inline=True)
    embed.add_field(name="Rate per Chapter", value=f"Rp {rate:,.0f}".replace(",", "."), inline=True)
    embed.add_field(name="Total Bayaran", value=f"Rp {total:,.0f}".replace(",", "."), inline=True)
    embed.add_field(
        name="Hasil Google Drive",
        value=assignment.get("gdrive_link") or "Link tidak tersimpan",
        inline=False,
    )
    embed.set_footer(text=f"Task #{assignment['id']} • Laporan akhir penyelesaian tugas")
    return embed


def build_revision_embed(assignment: dict, notes: str) -> discord.Embed:
    embed = discord.Embed(
        title="🔄 Tugas Perlu Revisi",
        description=(
            f"**{assignment['manga']}** chapter **{assignment['chapter']}** "
            "perlu diperbaiki sebelum dikirim ulang."
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(name="Catatan Administrator", value=notes, inline=False)
    if assignment.get("gdrive_link"):
        embed.add_field(name="Hasil Sebelumnya", value=assignment["gdrive_link"], inline=False)
    embed.set_footer(text=f"Task #{assignment['id']} • Perbaiki hasil lalu tekan Submit Hasil")
    return embed


async def _remove_review_card(interaction: discord.Interaction) -> None:
    """Remove a handled admin review card so staff-mod stays actionable."""
    if not interaction.message:
        return
    try:
        await interaction.message.delete()
    except discord.HTTPException:
        logger.warning("Could not remove processed review message %s", interaction.message.id)


class TicketSubmitModal(discord.ui.Modal, title="Submit Hasil Kerja"):
    gdrive_link = discord.ui.TextInput(label="Link Google Drive", placeholder="https://drive.google.com/...", required=True)
    catatan = discord.ui.TextInput(label="Catatan (Opsional)", placeholder="Catatan untuk admin...", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, assignment: dict):
        super().__init__()
        self.assignment_id = assignment["id"]

    async def on_submit(self, interaction: discord.Interaction):
        assignment = await _validated_assignment(interaction, self.assignment_id, ("claimed", "revision"))
        if not assignment:
            return
        link = self.gdrive_link.value.strip()
        if not link.startswith(("https://drive.google.com/", "http://drive.google.com/")):
            return await interaction.response.send_message("Masukkan link Google Drive yang valid dan dapat diakses admin.", ephemeral=True)
        if not await db.submit_assignment(assignment["id"], link, self.catatan.value or None):
            return await interaction.response.send_message("Submit gagal karena status tugas telah berubah. Coba buka panel terbaru.", ephemeral=True)
        confirmation = discord.Embed(title="Hasil Berhasil Dikirim", description="Hasil tugas sudah dikirim ke administrator untuk direview.", color=discord.Color.green())
        confirmation.add_field(name="Manga", value=assignment["manga"], inline=True)
        confirmation.add_field(name="Chapter", value=assignment["chapter"], inline=True)
        await interaction.response.send_message(embed=confirmation)
        log_channel = interaction.guild.get_channel(STAFF_LOG_CHANNEL_ID) if interaction.guild else None
        if log_channel:
            review = discord.Embed(title=f"Hasil Tugas #{assignment['id']} Siap Direview", description=f"**{assignment['manga']}** · Chapter **{assignment['chapter']}**", color=discord.Color.green())
            review.add_field(name="Staff", value=interaction.user.mention, inline=True)
            review.add_field(name="Role", value=assignment["role"], inline=True)
            review.add_field(name="Google Drive", value=link, inline=False)
            if self.catatan.value:
                review.add_field(name="Catatan Staff", value=self.catatan.value, inline=False)
            review.set_footer(text=f"Task #{assignment['id']} · Periksa izin Google Drive sebelum review.")
            await log_channel.send(embed=review, view=TicketReviewView(assignment["id"]))

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.exception("Submit interaction failed for task %s", self.assignment_id, exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("Terjadi kesalahan saat memproses hasil. Silakan coba lagi.", ephemeral=True)


async def approve_task(interaction: discord.Interaction, assignment_id: int):
    assignment = await _validated_assignment(interaction, assignment_id, ("submitted",), admin=True)
    if not assignment:
        return
    if not await db.approve_assignment(assignment_id):
        return await interaction.response.send_message("Approve gagal karena status tugas telah berubah.", ephemeral=True)
    assignment = await db.get_assignment(assignment_id)
    await interaction.response.defer(ephemeral=True)
    notified = await _notify_ticket(interaction, assignment, build_completed_embed(assignment))
    await _remove_review_card(interaction)
    await interaction.followup.send(
        (
            f"Tugas #{assignment_id} disetujui dan laporan akhir dikirim ke tiket staff."
            if notified
            else f"Tugas #{assignment_id} disetujui, tetapi tiket staff tidak ditemukan. Periksa tiket staff."
        ),
        ephemeral=True,
    )


class TicketReviseModal(discord.ui.Modal, title="Revisi Tugas"):
    catatan = discord.ui.TextInput(label="Catatan Revisi", placeholder="Jelaskan bagian yang perlu diperbaiki...", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, assignment_id: int):
        super().__init__()
        self.assignment_id = assignment_id

    async def on_submit(self, interaction: discord.Interaction):
        assignment = await _validated_assignment(interaction, self.assignment_id, ("submitted",), admin=True)
        if not assignment:
            return
        if not await db.revise_assignment(self.assignment_id, self.catatan.value):
            return await interaction.response.send_message("Revisi gagal karena status tugas telah berubah.", ephemeral=True)
        assignment = await db.get_assignment(self.assignment_id)
        await interaction.response.defer(ephemeral=True)
        notified = await _notify_ticket(
            interaction,
            assignment,
            build_revision_embed(assignment, self.catatan.value),
        )
        await _remove_review_card(interaction)
        await interaction.followup.send(
            (
                f"Revisi tugas #{self.assignment_id} sudah dikirim ke tiket staff."
                if notified
                else f"Revisi tersimpan, tetapi tiket staff tidak ditemukan. Periksa tiket staff."
            ),
            ephemeral=True,
        )


class SubmitDynamicItem(discord.ui.DynamicItem[discord.ui.Button], template=r"task:submit:(?P<assignment_id>\d+):v2"):
    def __init__(self, assignment_id: int):
        self.assignment_id = assignment_id
        super().__init__(discord.ui.Button(label="Submit Hasil", style=discord.ButtonStyle.success, custom_id=f"task:submit:{assignment_id}:v2"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["assignment_id"]))

    async def callback(self, interaction: discord.Interaction):
        assignment = await _validated_assignment(interaction, self.assignment_id, ("claimed", "revision"))
        if assignment:
            await interaction.response.send_modal(TicketSubmitModal(assignment))


class ApproveDynamicItem(discord.ui.DynamicItem[discord.ui.Button], template=r"task:approve:(?P<assignment_id>\d+):v2"):
    def __init__(self, assignment_id: int):
        self.assignment_id = assignment_id
        super().__init__(discord.ui.Button(label="Setuju", style=discord.ButtonStyle.success, custom_id=f"task:approve:{assignment_id}:v2"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["assignment_id"]))
    async def callback(self, interaction): await approve_task(interaction, self.assignment_id)


class ReviseDynamicItem(discord.ui.DynamicItem[discord.ui.Button], template=r"task:revise:(?P<assignment_id>\d+):v2"):
    def __init__(self, assignment_id: int):
        self.assignment_id = assignment_id
        super().__init__(discord.ui.Button(label="Revisi", style=discord.ButtonStyle.danger, custom_id=f"task:revise:{assignment_id}:v2"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["assignment_id"]))
    async def callback(self, interaction):
        assignment = await _validated_assignment(interaction, self.assignment_id, ("submitted",), admin=True)
        if assignment:
            await interaction.response.send_modal(TicketReviseModal(self.assignment_id))


class TicketSubmitView(discord.ui.View):
    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.add_item(SubmitDynamicItem(assignment_id))


class TicketReviewView(discord.ui.View):
    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.add_item(ApproveDynamicItem(assignment_id))
        self.add_item(ReviseDynamicItem(assignment_id))


class LegacyTaskView(discord.ui.View):
    """Compatibility handler for messages created before v2 IDs."""
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Submit Hasil", style=discord.ButtonStyle.success, custom_id="ticket_submit")
    async def legacy_submit(self, interaction, _button):
        assignment_id = task_id_from_message(interaction.message)
        if not assignment_id:
            return await interaction.response.send_message("Tombol lama ini tidak memiliki ID tugas. Buka `/menu` untuk panel terbaru.", ephemeral=True)
        assignment = await _validated_assignment(interaction, assignment_id, ("claimed", "revision"))
        if assignment: await interaction.response.send_modal(TicketSubmitModal(assignment))

    @discord.ui.button(label="Setuju", style=discord.ButtonStyle.success, custom_id="ticket_approve")
    async def legacy_approve(self, interaction, _button):
        assignment_id = task_id_from_message(interaction.message)
        if assignment_id: await approve_task(interaction, assignment_id)
        else: await interaction.response.send_message("ID tugas pada pesan lama tidak ditemukan.", ephemeral=True)

    @discord.ui.button(label="Revisi", style=discord.ButtonStyle.danger, custom_id="ticket_revise")
    async def legacy_revise(self, interaction, _button):
        assignment_id = task_id_from_message(interaction.message)
        if not assignment_id: return await interaction.response.send_message("ID tugas pada pesan lama tidak ditemukan.", ephemeral=True)
        assignment = await _validated_assignment(interaction, assignment_id, ("submitted",), admin=True)
        if assignment: await interaction.response.send_modal(TicketReviseModal(assignment_id))

import discord

from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import is_admin, is_staff
import database as db


class TicketSubmitView(discord.ui.View):
    """View for submitting work in a ticket channel."""

    function_name = "TicketSubmitView"

    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id

    @discord.ui.button(label="Submit Hasil", style=discord.ButtonStyle.success, custom_id="ticket_submit")
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        assignment = await db.get_assignment(self.assignment_id)

        if not assignment:
            return await interaction.response.send_message("Tugas tidak ditemukan!", ephemeral=False)

        if assignment["status"] not in ("claimed", "revision"):
            return await interaction.response.send_message("Tugas ini belum bisa di-submit!", ephemeral=False)

        if assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message(
                "Kamu hanya bisa submit tugas milikmu sendiri!",
                ephemeral=False,
            )

        await interaction.response.send_modal(TicketSubmitModal(assignment))


class TicketSubmitModal(discord.ui.Modal, title="Submit Hasil Kerja"):
    """Modal for submitting work."""

    function_name = "TicketSubmitModal"

    def __init__(self, assignment: dict):
        super().__init__()
        self.assignment_id = assignment["id"]

    gdrive_link = discord.ui.TextInput(
        label="Link Google Drive",
        placeholder="https://drive.google.com/...",
        style=discord.TextStyle.short,
        required=True,
    )

    catatan = discord.ui.TextInput(
        label="Catatan (Opsional)",
        placeholder="Catatan untuk admin...",
        style=discord.TextStyle.paragraph,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        assignment = await db.get_assignment(self.assignment_id)
        if not assignment:
            return await interaction.response.send_message("Tugas tidak ditemukan!", ephemeral=False)

        if not is_staff(interaction.user) or assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message(
                "Kamu hanya bisa submit tugas milikmu sendiri!",
                ephemeral=False,
            )

        if assignment["status"] not in ("claimed", "revision"):
            return await interaction.response.send_message("Tugas ini belum bisa di-submit!", ephemeral=False)

        success = await db.submit_assignment(
            assignment["id"],
            self.gdrive_link.value,
            self.catatan.value or None,
        )

        if not success:
            return await interaction.response.send_message("Gagal submit hasil!", ephemeral=False)

        embed = discord.Embed(
            title="Hasil Di-submit",
            description="Tugas kamu telah di-submit untuk review.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Manga", value=assignment["manga"], inline=True)
        embed.add_field(name="Chapter", value=assignment["chapter"], inline=True)
        embed.add_field(name="Link", value=self.gdrive_link.value, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=False)

        if interaction.channel:
            await interaction.channel.send(
                f"**{interaction.user.display_name}** telah submit hasil untuk "
                f"**{assignment['manga']}** chapter **{assignment['chapter']}**",
                view=TicketReviewView(assignment["id"]),
            )


class TicketReviewView(discord.ui.View):
    """View for admins to review a submitted assignment."""

    function_name = "TicketReviewView"

    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id

    @discord.ui.button(label="Setuju", style=discord.ButtonStyle.success, custom_id="ticket_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya admin yang bisa approve!", ephemeral=False)

        success = await db.approve_assignment(self.assignment_id)
        if not success:
            return await interaction.response.send_message("Gagal approve tugas!", ephemeral=False)

        assignment = await db.get_assignment(self.assignment_id)
        staff = interaction.guild.get_member(assignment["staff_id"]) if interaction.guild else None

        embed = discord.Embed(
            title="Tugas Disetujui",
            description=f"Chapter **{assignment['manga']}** telah disetujui.",
            color=discord.Color.green(),
        )

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

        if staff:
            try:
                await staff.send(
                    f"Tugas kamu untuk **{assignment['manga']}** chapter "
                    f"**{assignment['chapter']}** telah disetujui!"
                )
            except discord.DiscordException:
                pass

        if interaction.guild:
            log_channel = interaction.guild.get_channel(STAFF_LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(
                    f"**{interaction.user.display_name}** approve tugas: "
                    f"**{assignment['manga']}** chapter **{assignment['chapter']}**"
                )

    @discord.ui.button(label="Revisi", style=discord.ButtonStyle.danger, custom_id="ticket_revise")
    async def revise_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya admin yang bisa merevisi!", ephemeral=False)

        await interaction.response.send_modal(TicketReviseModal(self.assignment_id))


class TicketReviseModal(discord.ui.Modal, title="Revisi Tugas"):
    """Modal for requesting assignment revision."""

    function_name = "TicketReviseModal"

    def __init__(self, assignment_id: int):
        super().__init__()
        self.assignment_id = assignment_id

    catatan = discord.ui.TextInput(
        label="Catatan Revisi",
        placeholder="Jelaskan apa yang perlu diperbaiki...",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        success = await db.revise_assignment(self.assignment_id, self.catatan.value)
        if not success:
            return await interaction.response.send_message("Gagal merevisi tugas!", ephemeral=False)

        assignment = await db.get_assignment(self.assignment_id)
        staff = interaction.guild.get_member(assignment["staff_id"]) if interaction.guild else None

        embed = discord.Embed(
            title="Perlu Revisi",
            description=f"Chapter **{assignment['manga']}** perlu revisi.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Catatan", value=self.catatan.value, inline=False)

        await interaction.response.edit_message(embed=embed, view=None)

        if staff:
            try:
                await staff.send(
                    f"Tugas kamu untuk **{assignment['manga']}** chapter "
                    f"**{assignment['chapter']}** perlu revisi.\n"
                    f"Catatan: {self.catatan.value}"
                )
            except discord.DiscordException:
                pass

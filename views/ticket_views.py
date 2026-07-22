import discord

import database as db
from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import is_admin, is_staff


class TicketSubmitView(discord.ui.View):
    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id

    @discord.ui.button(label="Submit Hasil", style=discord.ButtonStyle.success, custom_id="ticket_submit")
    async def submit_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        assignment = await db.get_assignment(self.assignment_id)
        if not assignment:
            return await interaction.response.send_message("Tugas tidak ditemukan!", ephemeral=False)
        if assignment["status"] not in ("claimed", "revision"):
            return await interaction.response.send_message("Tugas ini belum bisa di-submit!", ephemeral=False)
        if assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message("Kamu hanya bisa submit tugas milikmu sendiri!", ephemeral=False)
        await interaction.response.send_modal(TicketSubmitModal(assignment))


class TicketSubmitModal(discord.ui.Modal, title="Submit Hasil Kerja"):
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

    def __init__(self, assignment: dict):
        super().__init__()
        self.assignment_id = assignment["id"]

    async def on_submit(self, interaction: discord.Interaction):
        assignment = await db.get_assignment(self.assignment_id)
        if not assignment:
            return await interaction.response.send_message("Tugas tidak ditemukan!", ephemeral=False)
        if not is_staff(interaction.user) or assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message("Kamu hanya bisa submit tugas milikmu sendiri!", ephemeral=False)
        if assignment["status"] not in ("claimed", "revision"):
            return await interaction.response.send_message("Tugas ini belum bisa di-submit!", ephemeral=False)
        link = self.gdrive_link.value.strip()
        if not link.startswith(("https://drive.google.com/", "http://drive.google.com/")):
            return await interaction.response.send_message("Masukkan link Google Drive yang valid.", ephemeral=False)

        if not await db.submit_assignment(assignment["id"], link, self.catatan.value or None):
            return await interaction.response.send_message("Gagal submit hasil!", ephemeral=False)

        confirmation = discord.Embed(
            title="Hasil Berhasil Dikirim",
            description="Hasil tugas sudah dikirim ke administrator untuk direview.",
            color=discord.Color.green(),
        )
        confirmation.add_field(name="Manga", value=assignment["manga"], inline=True)
        confirmation.add_field(name="Chapter", value=assignment["chapter"], inline=True)
        await interaction.response.send_message(embed=confirmation, ephemeral=False)

        log_channel = interaction.guild.get_channel(STAFF_LOG_CHANNEL_ID) if interaction.guild else None
        if log_channel:
            review = discord.Embed(
                title=f"Hasil Tugas #{assignment['id']} Siap Direview",
                description=f"**{assignment['manga']}** · Chapter **{assignment['chapter']}**",
                color=discord.Color.green(),
            )
            review.add_field(name="Staff", value=interaction.user.mention, inline=True)
            review.add_field(name="Role", value=assignment["role"], inline=True)
            review.add_field(name="Google Drive", value=link, inline=False)
            if self.catatan.value:
                review.add_field(name="Catatan Staff", value=self.catatan.value, inline=False)
            review.set_footer(text="Periksa izin akses Google Drive sebelum menyetujui tugas.")
            await log_channel.send(embed=review, view=TicketReviewView(assignment["id"]))


class TicketReviewView(discord.ui.View):
    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id

    @discord.ui.button(label="Setuju", style=discord.ButtonStyle.success, custom_id="ticket_approve")
    async def approve_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya admin yang bisa approve!", ephemeral=False)
        if not await db.approve_assignment(self.assignment_id):
            return await interaction.response.send_message("Gagal approve tugas!", ephemeral=False)
        assignment = await db.get_assignment(self.assignment_id)
        staff = interaction.guild.get_member(assignment["staff_id"]) if interaction.guild else None
        embed = discord.Embed(
            title="Tugas Disetujui",
            description=f"**{assignment['manga']}** chapter **{assignment['chapter']}** telah disetujui.",
            color=discord.Color.green(),
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        if staff:
            try:
                await staff.send(f"Tugas **{assignment['manga']}** chapter **{assignment['chapter']}** telah disetujui!")
            except discord.DiscordException:
                pass

    @discord.ui.button(label="Revisi", style=discord.ButtonStyle.danger, custom_id="ticket_revise")
    async def revise_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya admin yang bisa merevisi!", ephemeral=False)
        await interaction.response.send_modal(TicketReviseModal(self.assignment_id))


class TicketReviseModal(discord.ui.Modal, title="Revisi Tugas"):
    catatan = discord.ui.TextInput(
        label="Catatan Revisi",
        placeholder="Jelaskan apa yang perlu diperbaiki...",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    def __init__(self, assignment_id: int):
        super().__init__()
        self.assignment_id = assignment_id

    async def on_submit(self, interaction: discord.Interaction):
        if not await db.revise_assignment(self.assignment_id, self.catatan.value):
            return await interaction.response.send_message("Gagal merevisi tugas!", ephemeral=False)
        assignment = await db.get_assignment(self.assignment_id)
        staff = interaction.guild.get_member(assignment["staff_id"]) if interaction.guild else None
        embed = discord.Embed(
            title="Perlu Revisi",
            description=f"**{assignment['manga']}** chapter **{assignment['chapter']}** perlu revisi.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Catatan", value=self.catatan.value, inline=False)
        await interaction.response.edit_message(embed=embed, view=None)
        if staff:
            try:
                await staff.send(
                    f"Tugas **{assignment['manga']}** chapter **{assignment['chapter']}** perlu revisi.\n"
                    f"Catatan: {self.catatan.value}"
                )
            except discord.DiscordException:
                pass

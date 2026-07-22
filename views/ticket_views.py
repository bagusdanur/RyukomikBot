import asyncio
import io
import os
import re
import secrets
import zipfile

import boto3
import discord

from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import is_admin
import database as db


class TicketSubmitView(discord.ui.View):
    """View for submitting work in a ticket channel."""

    function_name = "TicketSubmitView"

    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id

    @discord.ui.button(label="Upload Hasil", style=discord.ButtonStyle.success, custom_id="ticket_submit")
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

        await interaction.response.send_modal(DiscordResultUploadModal(assignment))


class DiscordResultUploadModal(discord.ui.Modal, title="Upload Hasil Kerja"):
    def __init__(self, assignment: dict):
        super().__init__(timeout=600)
        self.assignment_id = assignment["id"]
        self.upload = discord.ui.FileUpload(custom_id="task_result_files", min_values=1, max_values=10)
        self.add_item(discord.ui.Label(
            text="Gambar hasil atau ZIP",
            description="Pilih maksimal 10 gambar. Jika lebih dari 10, kirim sebagai satu ZIP.",
            component=self.upload,
        ))

    async def on_submit(self, interaction: discord.Interaction):
        assignment = await db.get_assignment(self.assignment_id)
        if not assignment or assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message("Tugas ini bukan milikmu.", ephemeral=False)
        if assignment["status"] not in ("claimed", "revision"):
            return await interaction.response.send_message("Tugas ini tidak dapat di-submit pada status sekarang.", ephemeral=False)

        attachments = list(self.upload.values)
        allowed = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".zip", ".7z", ".rar", ".psd", ".clip"}
        invalid = [item.filename for item in attachments if os.path.splitext(item.filename)[1].lower() not in allowed]
        if invalid:
            return await interaction.response.send_message(
                f"Format tidak didukung: {', '.join(invalid[:3])}. Gunakan gambar, ZIP, 7Z, RAR, PSD, atau CLIP.",
                ephemeral=False,
            )

        await interaction.response.defer(ephemeral=False, thinking=True)
        files = []
        total_size = 0
        for attachment in sorted(attachments, key=lambda item: natural_key(item.filename)):
            data = await attachment.read()
            total_size += len(data)
            files.append((attachment.filename, data))
        if total_size > 500 * 1024 * 1024:
            return await interaction.followup.send("Total file terlalu besar. Maksimal 500 MB per submit.", ephemeral=False)

        if len(files) == 1 and os.path.splitext(files[0][0])[1].lower() in {".zip", ".7z", ".rar"}:
            output_name, payload = files[0]
            content_type = attachments[0].content_type or "application/octet-stream"
        else:
            buffer = io.BytesIO()
            width = max(3, len(str(len(files))))
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
                for index, (filename, data) in enumerate(files, 1):
                    extension = os.path.splitext(filename)[1].lower() or ".jpg"
                    archive.writestr(f"{index:0{width}d}{extension}", data)
            payload = buffer.getvalue()
            output_name = f"{safe_name(assignment['manga'])}-chapter-{safe_name(assignment['chapter'])}.zip"
            content_type = "application/zip"

        bucket = os.getenv("R2_BUCKET_NAME", "ryukomik-staff-submissions")
        key = "/".join((
            "submissions", safe_name(assignment["manga"]), f"chapter-{safe_name(assignment['chapter'])}",
            assignment["role"].replace("+", "-"), f"task-{assignment['id']}",
            f"{interaction.user.id}-{secrets.token_hex(4)}-{safe_name(output_name, keep_dot=True)}",
        ))
        try:
            client = boto3.client(
                "s3",
                endpoint_url=os.getenv("R2_ENDPOINT"),
                aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
                region_name="auto",
            )
            await asyncio.to_thread(
                client.put_object, Bucket=bucket, Key=key, Body=payload, ContentType=content_type
            )
            connection = await db.get_db()
            try:
                await connection.execute("""
                    INSERT INTO assignment_submissions
                        (assignment_id,staff_id,object_key,original_name,content_type,size_bytes,status,uploaded_at)
                    VALUES(?,?,?,?,?,?,'uploaded',CURRENT_TIMESTAMP)
                """, (assignment["id"], interaction.user.id, key, output_name, content_type, len(payload)))
                await connection.execute("""
                    UPDATE assignments SET status='submitted', submitted_at=CURRENT_TIMESTAMP,
                        gdrive_link=? WHERE id=? AND status IN ('claimed','revision')
                """, (f"r2://{bucket}/{key}", assignment["id"]))
                await connection.commit()
            finally:
                await connection.close()
        except Exception as error:
            print(f"[ERROR] Discord result upload failed: {error}")
            return await interaction.followup.send("Upload gagal disimpan. Coba lagi atau hubungi administrator.", ephemeral=False)

        embed = discord.Embed(
            title=f"Hasil Tugas #{assignment['id']} Siap Direview",
            description=f"**{assignment['manga']}** · Chapter **{assignment['chapter']}**",
            color=discord.Color.green(),
        )
        embed.add_field(name="Staff", value=interaction.user.mention, inline=True)
        embed.add_field(name="Role", value=assignment["role"], inline=True)
        embed.add_field(name="File", value=f"{output_name} · {len(payload) / 1024 / 1024:.1f} MB", inline=False)
        embed.set_footer(text="File tersimpan aman di R2 dan dapat diunduh melalui dashboard admin.")
        log_channel = interaction.guild.get_channel(STAFF_LOG_CHANNEL_ID) if interaction.guild else None
        if log_channel:
            await log_channel.send(embed=embed, view=TicketReviewView(assignment["id"]))
        await interaction.followup.send(
            f"✅ Hasil **{assignment['manga']} Chapter {assignment['chapter']}** berhasil dikirim ke <#{STAFF_LOG_CHANNEL_ID}>.",
            ephemeral=False,
        )


def natural_key(value: str):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]


def safe_name(value: str, keep_dot: bool = False) -> str:
    pattern = r"[^a-zA-Z0-9._-]+" if keep_dot else r"[^a-zA-Z0-9_-]+"
    return re.sub(pattern, "-", str(value)).strip("-._")[:100] or "file"


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

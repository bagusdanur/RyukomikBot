import asyncio
from typing import Optional

import discord
from discord.ext import commands

from config import REKRUT_CAT_ID, ROLE_ADMIN_ID, ROLE_STAFF_ID


TEST_MATERIALS = {
    "TL": "Tes TL: terjemahkan 1-2 halaman sample dan kirim link Google Drive di tombol submit.",
    "TS": "Tes TS: typeset 1-2 halaman sample dan kirim link Google Drive di tombol submit.",
    "TL+TS": "Tes TL+TS: terjemahkan dan typeset sample, lalu kirim link Google Drive di tombol submit.",
}


class RecruitmentView(discord.ui.View):
    """View for recruitment ticket creation."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Buat Tiket", style=discord.ButtonStyle.green, custom_id="rekrut_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user
        if not guild or not isinstance(member, discord.Member):
            return await interaction.response.send_message("Command ini hanya bisa dipakai di server.", ephemeral=False)

        for channel in guild.text_channels:
            if str(member.id) in (channel.topic or "") and channel.category_id == REKRUT_CAT_ID:
                return await interaction.response.send_message(
                    f"Kamu sudah memiliki tiket rekrutmen: {channel.mention}",
                    ephemeral=False,
                )

        await interaction.response.defer(ephemeral=False)

        admin_role = guild.get_role(ROLE_ADMIN_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
            ),
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            )

        category = guild.get_channel(REKRUT_CAT_ID)
        safe_name = "".join(ch for ch in member.name.lower() if ch.isalnum() or ch == "-")
        ticket_channel = await guild.create_text_channel(
            name=f"tiket-{safe_name}-{str(member.id)[-4:]}",
            category=category,
            overwrites=overwrites,
            topic=f"Tiket rekrutmen untuk {member.display_name} ({member.id})",
        )

        embed = discord.Embed(
            title="Tiket Rekrutmen",
            description=(
                f"Selamat datang {member.mention}.\n"
                "Pilih posisi yang ingin dilamar, lalu bot akan mengirim bahan tes."
            ),
            color=discord.Color.green(),
        )
        await ticket_channel.send(embed=embed, view=RecruitmentPositionView(member.id))
        await interaction.followup.send(f"Tiket rekrutmen berhasil dibuat: {ticket_channel.mention}", ephemeral=False)


class RecruitmentPositionView(discord.ui.View):
    """Applicant position selector."""

    def __init__(self, applicant_id: int):
        super().__init__(timeout=None)
        self.add_item(RecruitmentPositionSelect(applicant_id))


class RecruitmentPositionSelect(discord.ui.Select):
    def __init__(self, applicant_id: int):
        self.applicant_id = applicant_id
        options = [
            discord.SelectOption(label="TL", description="Translator", value="TL"),
            discord.SelectOption(label="TS", description="Typesetter", value="TS"),
            discord.SelectOption(label="TL+TS", description="Translator + Typesetter", value="TL+TS"),
        ]
        super().__init__(
            placeholder="Pilih posisi...",
            options=options,
            custom_id=f"rekrut_position:{applicant_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.applicant_id:
            return await interaction.response.send_message("Hanya pemilik tiket yang bisa memilih posisi.", ephemeral=False)

        position = self.values[0]
        embed = discord.Embed(
            title=f"Bahan Tes {position}",
            description=TEST_MATERIALS[position],
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=RecruitmentSubmitView(self.applicant_id, position),
            ephemeral=False,
        )


class RecruitmentSubmitView(discord.ui.View):
    def __init__(self, applicant_id: int, position: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.position = position

    @discord.ui.button(label="Submit Hasil Tes", style=discord.ButtonStyle.success, custom_id="rekrut_submit")
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.applicant_id:
            return await interaction.response.send_message("Hanya pemilik tiket yang bisa submit tes.", ephemeral=False)
        await interaction.response.send_modal(RecruitmentSubmitModal(self.applicant_id, self.position))


class RecruitmentSubmitModal(discord.ui.Modal, title="Submit Hasil Tes"):
    def __init__(self, applicant_id: int, position: str):
        super().__init__()
        self.applicant_id = applicant_id
        self.position = position

    gdrive_link = discord.ui.TextInput(
        label="Link Google Drive",
        placeholder="https://drive.google.com/...",
        style=discord.TextStyle.short,
        required=True,
    )

    notes = discord.ui.TextInput(
        label="Catatan (Opsional)",
        placeholder="Catatan untuk admin...",
        style=discord.TextStyle.paragraph,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Hasil Tes Rekrutmen",
            description=f"Posisi: **{self.position}**",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Applicant", value=interaction.user.mention, inline=True)
        embed.add_field(name="Link", value=self.gdrive_link.value, inline=False)
        if self.notes.value:
            embed.add_field(name="Catatan", value=self.notes.value, inline=False)
        await interaction.response.send_message(
            embed=embed,
            view=RecruitmentReviewView(self.applicant_id, self.position),
            ephemeral=False,
        )


class RecruitmentReviewView(discord.ui.View):
    def __init__(self, applicant_id: int, position: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.position = position

    @discord.ui.button(label="Approve Staff", style=discord.ButtonStyle.success, custom_id="rekrut_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Hanya admin yang bisa approve rekrutmen.", ephemeral=False)

        guild = interaction.guild
        applicant = guild.get_member(self.applicant_id) if guild else None
        staff_role = guild.get_role(ROLE_STAFF_ID) if guild else None
        if not applicant or not staff_role:
            return await interaction.response.send_message("Applicant atau role Staff tidak ditemukan.", ephemeral=False)

        await applicant.add_roles(staff_role, reason=f"Recruitment approved for {self.position}")
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"{applicant.mention} diterima sebagai Staff untuk posisi {self.position}.", ephemeral=False)


class RecruitmentBot:
    """Recruitment system functionality."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def setup(self):
        self.bot.add_view(RecruitmentView())

        @self.bot.command(name="rekrut")
        async def rekrut_command(ctx: commands.Context):
            if not ctx.author.guild_permissions.administrator:
                return await ctx.send("Hanya admin yang bisa menggunakan command ini!")

            embed = discord.Embed(
                title="Rekrutmen Ryukomik",
                description="Klik tombol di bawah untuk membuka tiket rekrutmen.",
                color=discord.Color.green(),
            )
            await ctx.send(embed=embed, view=RecruitmentView())
            await ctx.message.delete()

        @self.bot.command(name="close")
        async def close_ticket(ctx: commands.Context):
            if not ctx.channel.category_id or ctx.channel.category_id != REKRUT_CAT_ID:
                return await ctx.send("Command ini hanya bisa digunakan di tiket rekrutmen!")

            if not ctx.author.guild_permissions.administrator:
                if str(ctx.author.id) not in (ctx.channel.topic or ""):
                    return await ctx.send("Kamu tidak memiliki akses ke tiket ini!")

            embed = discord.Embed(
                title="Tiket Ditutup",
                description="Tiket ini akan ditutup dalam 5 detik...",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await ctx.channel.delete()


def setup_recruitment(bot: commands.Bot):
    """Setup recruitment system."""
    recruitment = RecruitmentBot(bot)
    recruitment.setup()
    return recruitment

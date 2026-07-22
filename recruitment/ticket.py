import asyncio
import re
from typing import Optional

import discord
from discord.ext import commands

from config import REKRUT_CAT_ID, ROLE_STAFF_ID
from helpers.utils import (
    build_private_ticket_name,
    build_private_ticket_overwrites,
    find_or_create_staff_ticket,
    is_admin,
)
from panels.staff_panel import upsert_staff_panel


POSITIONS = ("TL", "TS", "TL+TS")
POSITION_IDS = {"TL": "tl", "TS": "ts", "TL+TS": "tl_ts"}
TEST_MATERIALS = {
    "TL": "Terjemahkan 1-2 halaman sampel ke Bahasa Indonesia, lalu unggah hasilnya ke Google Drive.",
    "TS": "Kerjakan cleaning, redrawing, dan typesetting untuk 1-2 halaman sampel, lalu unggah ke Google Drive.",
    "TL+TS": "Terjemahkan sekaligus typeset 1-2 halaman sampel, lalu unggah hasilnya ke Google Drive.",
}


def build_recruitment_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Ryukomik | Staff Recruitment",
        description="Halo! Ryukomik sedang membuka kesempatan untuk bergabung sebagai staff scanlation.",
        color=discord.Color.from_rgb(88, 101, 242),
    )
    embed.add_field(
        name="💬 TL — Translator",
        value="Menerjemahkan dialog dari Bahasa Inggris ke Bahasa Indonesia secara natural dan mudah dibaca.",
        inline=False,
    )
    embed.add_field(
        name="🎨 TS — Typesetter / Editor",
        value="Menangani cleaning, redrawing, dan typesetting agar chapter siap dirilis.",
        inline=False,
    )
    embed.add_field(
        name="📌 Persyaratan",
        value=(
            "• Memiliki waktu luang dan bertanggung jawab.\n"
            "• Bisa berkomunikasi serta menerima revisi.\n"
            "• Memiliki perangkat yang memadai; PC/laptop sangat disarankan untuk TS."
        ),
        inline=False,
    )
    embed.add_field(
        name="🔒 Tiket Privat",
        value=(
            "Tekan tombol di bawah untuk membuat tiket pendaftaran. Tiket hanya dapat dilihat "
            "oleh kamu, administrator, dan bot."
        ),
        inline=False,
    )
    embed.set_footer(text="Ryukomik Official • Recruitment System")
    return embed


def build_ticket_overwrites(guild: discord.Guild, applicant: discord.Member):
    return build_private_ticket_overwrites(guild, applicant)


def build_ticket_topic(applicant_id: int, position: str = "pending") -> str:
    return f"Tiket rekrutmen | applicant_id={applicant_id} | position={position}"


def get_topic_position(channel: discord.TextChannel) -> Optional[str]:
    match = re.search(r"position=(TL\+TS|TL|TS)", channel.topic or "", re.IGNORECASE)
    return match.group(1).upper() if match else None


def get_ticket_owner(channel: discord.TextChannel) -> Optional[discord.Member]:
    topic = channel.topic or ""
    match = re.search(r"applicant_id=(\d+)", topic)
    if not match:
        match = re.search(r"\((\d{15,22})\)", topic)
    if match:
        member = channel.guild.get_member(int(match.group(1)))
        if member:
            return member

    for target, overwrite in channel.overwrites.items():
        if (
            isinstance(target, discord.Member)
            and channel.guild.me
            and target.id != channel.guild.me.id
            and overwrite.view_channel is not False
        ):
            return target
    return None


def is_recruitment_panel(message: discord.Message) -> bool:
    return bool(
        message.guild
        and message.guild.me
        and message.author.id == message.guild.me.id
        and message.embeds
        and "recruit" in (message.embeds[0].title or "").casefold()
    )


async def upsert_recruitment_panel(channel: discord.TextChannel) -> tuple[discord.Message, int]:
    panels = [message async for message in channel.history(limit=100) if is_recruitment_panel(message)]
    if panels:
        primary = panels[0]
        await primary.edit(embed=build_recruitment_panel_embed(), view=RecruitmentView())
        disabled = 0
        for duplicate in panels[1:]:
            if duplicate.components:
                await duplicate.edit(view=None)
                disabled += 1
        return primary, disabled

    message = await channel.send(embed=build_recruitment_panel_embed(), view=RecruitmentView())
    return message, 0


class RecruitmentBaseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        print(f"[ERROR] Recruitment interaction failed: {error}")
        message = "Terjadi kesalahan saat memproses rekrutmen. Hubungi administrator."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=False)
        else:
            await interaction.response.send_message(message, ephemeral=False)


class RecruitmentView(RecruitmentBaseView):
    @discord.ui.button(
        label="Buat Tiket Pendaftaran",
        emoji="📩",
        style=discord.ButtonStyle.primary,
        custom_id="recruitment:create_ticket:v1",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user
        if not guild or not isinstance(member, discord.Member):
            return await interaction.response.send_message("Tombol ini hanya bisa digunakan di server.", ephemeral=False)

        category = guild.get_channel(REKRUT_CAT_ID)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message(
                "Kategori rekrutmen belum tersedia. Hubungi administrator.", ephemeral=False
            )

        for channel in category.text_channels:
            owner = get_ticket_owner(channel)
            if owner and owner.id == member.id:
                return await interaction.response.send_message(
                    f"Kamu sudah memiliki tiket privat: {channel.mention}", ephemeral=False
                )

        await interaction.response.defer(ephemeral=False)
        ticket_channel = await guild.create_text_channel(
            name=build_private_ticket_name(member),
            category=category,
            overwrites=build_ticket_overwrites(guild, member),
            topic=build_ticket_topic(member.id),
            reason=f"Tiket rekrutmen untuk {member}",
        )
        await ticket_channel.edit(
            overwrites=build_ticket_overwrites(guild, member),
            sync_permissions=False,
            reason="Mengunci tiket rekrutmen",
        )

        embed = discord.Embed(
            title="Selamat Datang di Tiket Rekrutmen",
            description=(
                f"Halo {member.mention}. Pilih posisi yang ingin kamu lamar melalui menu di bawah.\n\n"
                "Tiket ini privat dan seluruh proses pendaftaran dilakukan di sini."
            ),
            color=discord.Color.green(),
        )
        await ticket_channel.send(embed=embed, view=RecruitmentPositionView())
        await interaction.followup.send(f"Tiket berhasil dibuat: {ticket_channel.mention}", ephemeral=False)


class RecruitmentPositionView(RecruitmentBaseView):
    def __init__(self):
        super().__init__()
        self.add_item(RecruitmentPositionSelect())


class RecruitmentPositionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="TL", description="Translator", value="TL", emoji="💬"),
            discord.SelectOption(label="TS", description="Typesetter / Editor", value="TS", emoji="🎨"),
            discord.SelectOption(label="TL+TS", description="Translator sekaligus Typesetter", value="TL+TS", emoji="✨"),
        ]
        super().__init__(
            placeholder="Pilih posisi yang ingin dilamar...",
            options=options,
            custom_id="recruitment:position:v1",
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Tiket tidak valid.", ephemeral=False)
        owner = get_ticket_owner(interaction.channel)
        if not owner or interaction.user.id != owner.id:
            return await interaction.response.send_message("Hanya pemilik tiket yang dapat memilih posisi.", ephemeral=False)

        position = self.values[0]
        await interaction.channel.edit(
            topic=build_ticket_topic(owner.id, position),
            reason=f"Posisi rekrutmen dipilih: {position}",
        )
        embed = discord.Embed(
            title=f"Bahan Tes {position}",
            description=TEST_MATERIALS[position],
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Cara Mengirim",
            value="Selesaikan tes, unggah ke Google Drive, lalu tekan **Submit Hasil Tes**.",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, view=RecruitmentSubmitView(position), ephemeral=False)


class RecruitmentSubmitView(RecruitmentBaseView):
    def __init__(self, position: str):
        self.position = position
        super().__init__()
        button = discord.ui.Button(
            label="Submit Hasil Tes",
            emoji="📤",
            style=discord.ButtonStyle.success,
            custom_id=f"recruitment:submit:{POSITION_IDS[position]}:v1",
        )
        button.callback = self.submit_button
        self.add_item(button)

    async def submit_button(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Tiket tidak valid.", ephemeral=False)
        owner = get_ticket_owner(interaction.channel)
        if not owner or interaction.user.id != owner.id:
            return await interaction.response.send_message("Hanya pemilik tiket yang dapat submit tes.", ephemeral=False)
        if get_topic_position(interaction.channel) != self.position:
            return await interaction.response.send_message("Posisi tiket tidak sesuai. Pilih posisi kembali.", ephemeral=False)
        await interaction.response.send_modal(RecruitmentSubmitModal(self.position))


class RecruitmentSubmitModal(discord.ui.Modal, title="Submit Hasil Tes"):
    gdrive_link = discord.ui.TextInput(
        label="Link Google Drive",
        placeholder="https://drive.google.com/...",
        required=True,
    )
    notes = discord.ui.TextInput(
        label="Catatan (Opsional)",
        placeholder="Tambahkan informasi untuk administrator...",
        style=discord.TextStyle.paragraph,
        required=False,
    )

    def __init__(self, position: str):
        super().__init__()
        self.position = position

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Tiket tidak valid.", ephemeral=False)
        owner = get_ticket_owner(interaction.channel)
        if not owner or interaction.user.id != owner.id:
            return await interaction.response.send_message("Hanya pemilik tiket yang dapat submit tes.", ephemeral=False)
        if not self.gdrive_link.value.startswith(("https://drive.google.com/", "http://drive.google.com/")):
            return await interaction.response.send_message("Gunakan link Google Drive yang valid.", ephemeral=False)

        embed = discord.Embed(
            title="Hasil Tes Menunggu Review",
            description=f"Posisi: **{self.position}**",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Pelamar", value=owner.mention, inline=True)
        embed.add_field(name="Link Hasil", value=self.gdrive_link.value, inline=False)
        if self.notes.value:
            embed.add_field(name="Catatan", value=self.notes.value, inline=False)
        await interaction.response.send_message(
            embed=embed,
            view=RecruitmentReviewView(self.position),
            ephemeral=False,
        )


class RecruitmentReviewView(RecruitmentBaseView):
    def __init__(self, position: str):
        self.position = position
        super().__init__()
        button = discord.ui.Button(
            label="Approve Staff",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"recruitment:approve:{POSITION_IDS[position]}:v1",
        )
        button.callback = self.approve_button
        self.add_item(button)

    async def approve_button(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator yang dapat approve.", ephemeral=False)
        if not isinstance(interaction.channel, discord.TextChannel) or not interaction.guild:
            return await interaction.response.send_message("Tiket tidak valid.", ephemeral=False)

        applicant = get_ticket_owner(interaction.channel)
        staff_role = interaction.guild.get_role(ROLE_STAFF_ID)
        if not applicant:
            return await interaction.response.send_message("Pemilik tiket tidak ditemukan.", ephemeral=False)
        if not staff_role:
            return await interaction.response.send_message("Role Staff belum dikonfigurasi.", ephemeral=False)

        await applicant.add_roles(staff_role, reason=f"Lulus rekrutmen posisi {self.position}")
        ticket = await find_or_create_staff_ticket(interaction.guild, applicant)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await ticket.send(content=f"Selamat {applicant.mention}, kamu diterima sebagai staff posisi **{self.position}**.")
        await upsert_staff_panel(ticket, applicant)


class RecruitmentBot:
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def register_persistent_views(self):
        self.bot.add_view(RecruitmentView())
        self.bot.add_view(RecruitmentPositionView())
        for position in POSITIONS:
            self.bot.add_view(RecruitmentSubmitView(position))
            self.bot.add_view(RecruitmentReviewView(position))

    def setup(self):
        @self.bot.command(name="rekrut")
        async def rekrut_command(ctx: commands.Context):
            if not is_admin(ctx.author):
                return await ctx.send("Hanya administrator yang dapat memasang panel rekrutmen.")
            if not isinstance(ctx.channel, discord.TextChannel):
                return await ctx.send("Command ini hanya dapat digunakan di text channel.")
            message, disabled = await upsert_recruitment_panel(ctx.channel)
            await ctx.send(
                f"Panel rekrutmen aktif: {message.jump_url}. Panel lama dinonaktifkan: **{disabled}**."
            )
            try:
                await ctx.message.delete()
            except discord.DiscordException:
                pass

        @self.bot.tree.command(name="setup-rekrutmen", description="Pasang atau perbaiki panel rekrutmen")
        async def setup_recruitment_command(interaction: discord.Interaction):
            if not is_admin(interaction.user):
                return await interaction.response.send_message("Hanya administrator yang dapat menggunakan command ini.", ephemeral=False)
            if not isinstance(interaction.channel, discord.TextChannel):
                return await interaction.response.send_message("Gunakan command ini di text channel rekrutmen.", ephemeral=False)
            await interaction.response.defer(ephemeral=False)
            message, disabled = await upsert_recruitment_panel(interaction.channel)
            await interaction.followup.send(
                f"Panel rekrutmen aktif: {message.jump_url}. Panel lama dinonaktifkan: **{disabled}**.",
                ephemeral=False,
            )

        @self.bot.command(name="close")
        async def close_ticket(ctx: commands.Context):
            if (
                ctx.channel.category_id != REKRUT_CAT_ID
                or not (ctx.channel.topic or "").startswith("Tiket rekrutmen")
            ):
                return await ctx.send("Command ini hanya bisa digunakan di tiket rekrutmen.")
            owner = get_ticket_owner(ctx.channel)
            if not is_admin(ctx.author) and (not owner or owner.id != ctx.author.id):
                return await ctx.send("Kamu tidak memiliki akses untuk menutup tiket ini.")
            await ctx.send(embed=discord.Embed(
                title="Tiket Ditutup",
                description="Tiket akan dihapus dalam 5 detik.",
                color=discord.Color.red(),
            ))
            await asyncio.sleep(5)
            await ctx.channel.delete(reason=f"Tiket ditutup oleh {ctx.author}")

        @self.bot.command(name="fix-rekrut")
        async def fix_recruitment_permissions(ctx: commands.Context, scope: str = "channel"):
            if not ctx.guild or not is_admin(ctx.author):
                return await ctx.send("Hanya administrator yang dapat memperbaiki permission tiket.")
            if scope.casefold() == "semua":
                category = ctx.guild.get_channel(REKRUT_CAT_ID)
                channels = list(category.text_channels) if isinstance(category, discord.CategoryChannel) else []
            elif ctx.channel.category_id == REKRUT_CAT_ID:
                channels = [ctx.channel]
            else:
                return await ctx.send("Gunakan di dalam tiket, atau jalankan `!fix-rekrut semua`.")

            fixed = 0
            skipped = 0
            for channel in channels:
                topic = channel.topic or ""
                if "tiket" not in channel.name and not topic.startswith(("Tiket rekrutmen", "Tiket staff")):
                    continue
                owner = get_ticket_owner(channel)
                if not owner:
                    skipped += 1
                    continue
                await channel.edit(
                    name=build_private_ticket_name(owner),
                    topic=(
                        f"Tiket staff untuk {owner.display_name} ({owner.id})"
                        if discord.utils.get(owner.roles, id=ROLE_STAFF_ID)
                        else build_ticket_topic(owner.id, get_topic_position(channel) or "pending")
                    ),
                    overwrites=build_ticket_overwrites(ctx.guild, owner),
                    sync_permissions=False,
                    reason=f"Permission diperbaiki oleh {ctx.author}",
                )
                fixed += 1
            await ctx.send(f"Permission selesai. Berhasil: **{fixed}**, dilewati: **{skipped}**.")


def setup_recruitment(bot: commands.Bot):
    recruitment = RecruitmentBot(bot)
    recruitment.setup()
    return recruitment

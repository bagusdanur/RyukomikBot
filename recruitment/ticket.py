import asyncio
import re
from typing import Optional

import discord
from discord.ext import commands

import database as db
from config import REKRUT_CAT_ID, ROLE_STAFF_ID, STAFF_LOG_CHANNEL_ID
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
    "TL": "Unduh paket **Tes TL** dan instruksinya dari website Ryukomik, lalu terjemahkan sesuai petunjuk.",
    "TS": "Unduh paket **Tes TS**, instruksi, dan referensi terjemahan dari website Ryukomik, lalu kerjakan sesuai petunjuk.",
    "TL+TS": "Kerjakan kedua paket **Tes TL** dan **Tes TS** dari website Ryukomik sesuai instruksi masing-masing.",
}
RECRUITMENT_FILES_URL = "https://ryukomik.web.id/files/rekrutmen"
TEST_LINKS = {
    "TL": (
        ("Download Tes TL", f"{RECRUITMENT_FILES_URL}/TL_Test.zip", "📦"),
        ("Instruksi TL", f"{RECRUITMENT_FILES_URL}/instruksi_tl.txt", "📄"),
    ),
    "TS": (
        ("Download Tes TS", f"{RECRUITMENT_FILES_URL}/TS_Test.zip", "📦"),
        ("Instruksi TS", f"{RECRUITMENT_FILES_URL}/instruksi_ts.txt", "📄"),
        ("Referensi Terjemahan", f"{RECRUITMENT_FILES_URL}/terjemahan_ts.txt", "📝"),
    ),
    "TL+TS": (
        ("Download Tes TL", f"{RECRUITMENT_FILES_URL}/TL_Test.zip", "📦"),
        ("Instruksi TL", f"{RECRUITMENT_FILES_URL}/instruksi_tl.txt", "📄"),
        ("Download Tes TS", f"{RECRUITMENT_FILES_URL}/TS_Test.zip", "📦"),
        ("Instruksi TS", f"{RECRUITMENT_FILES_URL}/instruksi_ts.txt", "📄"),
        ("Referensi TS", f"{RECRUITMENT_FILES_URL}/terjemahan_ts.txt", "📝"),
    ),
}


def build_review_embed(submission: dict, applicant: discord.Member | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"Hasil Tes Rekrutmen #{submission['id']}",
        description="Hasil tes baru menunggu review Administrator.",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="Pelamar",
        value=applicant.mention if applicant else f"<@{submission['applicant_id']}>",
        inline=True,
    )
    embed.add_field(name="Posisi", value=submission["position"], inline=True)
    embed.add_field(name="Tiket Pelamar", value=f"<#{submission['ticket_channel_id']}>", inline=True)
    embed.add_field(name="Link Hasil", value=submission["gdrive_link"], inline=False)
    if submission.get("notes"):
        embed.add_field(name="Catatan", value=submission["notes"], inline=False)
    embed.set_footer(text=f"Recruitment #{submission['id']} • Review hanya oleh Administrator")
    return embed


async def publish_recruitment_review(
    guild: discord.Guild,
    submission: dict,
    applicant: discord.Member | None = None,
) -> discord.Message:
    """Upsert the one actionable review card in staff-mod."""
    channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("Channel staff-mod tidak ditemukan.")
    embed = build_review_embed(submission, applicant)
    message = None
    if submission.get("review_message_id"):
        try:
            message = await channel.fetch_message(int(submission["review_message_id"]))
            await message.edit(embed=embed, view=RecruitmentReviewView(int(submission["id"])))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = None
    if message is None:
        message = await channel.send(
            embed=embed,
            view=RecruitmentReviewView(int(submission["id"])),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await db.set_recruitment_review_message(int(submission["id"]), message.id)
    return message


def build_test_embed(position: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"Bahan Tes {position}",
        description=TEST_MATERIALS[position],
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Cara Mengerjakan",
        value=(
            "1. Tekan tombol download di bawah.\n"
            "2. Baca file instruksi sampai selesai.\n"
            "3. Kerjakan bahan tes sesuai posisi yang dipilih.\n"
            "4. Unggah hasil ke Google Drive, lalu tekan **Submit Hasil Tes**."
        ),
        inline=False,
    )
    embed.set_footer(text="Bahan resmi berasal dari website Ryukomik")
    return embed


def build_recruitment_panel_embed(enabled_positions=None) -> discord.Embed:
    enabled = set(POSITIONS if enabled_positions is None else enabled_positions)
    embed = discord.Embed(
        title="Ryukomik | Staff Recruitment",
        description=(
            "Halo! Ryukomik sedang membuka kesempatan untuk bergabung sebagai staff scanlation."
            if enabled
            else "Rekrutmen staff sedang ditutup sementara. Silakan pantau panel ini untuk pembukaan berikutnya."
        ),
        color=discord.Color.from_rgb(88, 101, 242),
    )
    position_fields = {
        "TL": (
            "💬 TL — Translator",
            "Menerjemahkan dialog dari Bahasa Inggris ke Bahasa Indonesia secara natural dan mudah dibaca.",
        ),
        "TS": (
            "🎨 TS — Typesetter / Editor",
            "Menangani cleaning, redrawing, dan typesetting agar chapter siap dirilis.",
        ),
        "TL+TS": (
            "✨ TL + TS — Keduanya",
            "Mengerjakan paket tes Translator dan Typesetter untuk posisi gabungan.",
        ),
    }
    for position in POSITIONS:
        name, description = position_fields[position]
        is_open = position in enabled
        embed.add_field(
            name=name if is_open else f"{name} • CLOSED",
            value=description if is_open else f"{description}\n🔒 **Pendaftaran posisi ini sedang ditutup.**",
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
    if enabled:
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
    settings = await db.get_recruitment_position_settings()
    enabled = [position for position in POSITIONS if settings[position]]
    panels = [message async for message in channel.history(limit=100) if is_recruitment_panel(message)]
    if panels:
        primary = panels[0]
        await primary.edit(
            embed=build_recruitment_panel_embed(enabled),
            view=RecruitmentView(enabled),
        )
        disabled = 0
        for duplicate in panels[1:]:
            if duplicate.components:
                await duplicate.edit(view=None)
                disabled += 1
        return primary, disabled

    message = await channel.send(
        embed=build_recruitment_panel_embed(enabled),
        view=RecruitmentView(enabled),
    )
    return message, 0


async def reconcile_legacy_recruitment_reviews(guild: discord.Guild) -> int:
    """Move active legacy review cards from applicant tickets to staff-mod once."""
    category = guild.get_channel(REKRUT_CAT_ID)
    if not isinstance(category, discord.CategoryChannel):
        return 0
    moved = 0
    for channel in category.text_channels:
        applicant = get_ticket_owner(channel)
        if not applicant:
            continue
        async for message in channel.history(limit=100):
            if not message.embeds or not message.components:
                continue
            embed = message.embeds[0]
            if embed.title != "Hasil Tes Menunggu Review":
                continue
            position_match = re.search(
                r"Posisi:\s*\*\*(TL\+TS|TL|TS)\*\*",
                embed.description or "",
                re.IGNORECASE,
            )
            position = position_match.group(1).upper() if position_match else get_topic_position(channel)
            fields = {field.name: field.value for field in embed.fields}
            link = fields.get("Link Hasil", "")
            if position not in POSITIONS or not link.startswith(("https://drive.google.com/", "http://drive.google.com/")):
                continue
            submission = await db.upsert_recruitment_submission(
                applicant.id,
                position,
                channel.id,
                link,
                fields.get("Catatan"),
            )
            await publish_recruitment_review(guild, submission, applicant)
            await message.edit(view=None)
            moved += 1
    return moved


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
        in_private_ticket = isinstance(interaction.channel, discord.TextChannel) and (
            interaction.channel.topic or ""
        ).startswith("Tiket rekrutmen")
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=not in_private_ticket)
        else:
            await interaction.response.send_message(message, ephemeral=not in_private_ticket)


class RecruitmentView(RecruitmentBaseView):
    def __init__(self, enabled_positions=None):
        super().__init__()
        enabled = set(POSITIONS if enabled_positions is None else enabled_positions)
        for item in self.children:
            if getattr(item, "custom_id", None) == "recruitment:create_ticket:v1":
                item.disabled = not enabled

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
            return await interaction.response.send_message("Tombol ini hanya bisa digunakan di server.", ephemeral=True)

        settings = await db.get_recruitment_position_settings()
        enabled = [position for position in POSITIONS if settings[position]]
        if not enabled:
            return await interaction.response.send_message(
                "Rekrutmen sedang ditutup. Silakan tunggu pengumuman berikutnya.",
                ephemeral=True,
            )

        category = guild.get_channel(REKRUT_CAT_ID)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message(
                "Kategori rekrutmen belum tersedia. Hubungi administrator.", ephemeral=True
            )

        for channel in category.text_channels:
            owner = get_ticket_owner(channel)
            if owner and owner.id == member.id:
                return await interaction.response.send_message(
                    f"Kamu sudah memiliki tiket privat: {channel.mention}", ephemeral=True
                )

        await interaction.response.defer(ephemeral=True)
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
        await ticket_channel.send(embed=embed, view=RecruitmentPositionView(enabled))
        await interaction.followup.send(f"Tiket privat berhasil dibuat: {ticket_channel.mention}", ephemeral=True)


class RecruitmentPositionView(RecruitmentBaseView):
    def __init__(self, enabled_positions=None):
        super().__init__()
        enabled = POSITIONS if enabled_positions is None else tuple(enabled_positions)
        if enabled:
            self.add_item(RecruitmentPositionSelect(enabled))


class RecruitmentPositionSelect(discord.ui.Select):
    def __init__(self, enabled_positions=POSITIONS):
        all_options = [
            discord.SelectOption(label="TL", description="Translator", value="TL", emoji="💬"),
            discord.SelectOption(label="TS", description="Typesetter / Editor", value="TS", emoji="🎨"),
            discord.SelectOption(label="TL+TS", description="Translator sekaligus Typesetter", value="TL+TS", emoji="✨"),
        ]
        enabled = set(enabled_positions)
        options = [option for option in all_options if option.value in enabled]
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
        settings = await db.get_recruitment_position_settings()
        if not settings.get(position, False):
            enabled = [item for item in POSITIONS if settings[item]]
            embed = discord.Embed(
                title="Posisi Tidak Lagi Dibuka",
                description=(
                    "Posisi yang dipilih baru saja ditutup. Pilih posisi lain yang masih tersedia."
                    if enabled
                    else "Seluruh posisi rekrutmen sedang ditutup. Tiket ini dapat digunakan kembali saat rekrutmen dibuka."
                ),
                color=discord.Color.orange(),
            )
            return await interaction.response.edit_message(
                embed=embed,
                view=RecruitmentPositionView(enabled),
            )
        await interaction.channel.edit(
            topic=build_ticket_topic(owner.id, position),
            reason=f"Posisi rekrutmen dipilih: {position}",
        )
        await interaction.response.send_message(
            embed=build_test_embed(position), view=RecruitmentSubmitView(position), ephemeral=False
        )


class RecruitmentSubmitView(RecruitmentBaseView):
    def __init__(self, position: str):
        self.position = position
        super().__init__()
        button = discord.ui.Button(
            label="Submit Hasil Tes",
            emoji="📤",
            style=discord.ButtonStyle.success,
            custom_id=f"recruitment:submit:{POSITION_IDS[position]}:v1",
            row=1,
        )
        button.callback = self.submit_button
        self.add_item(button)
        for label, url, emoji in TEST_LINKS[position]:
            self.add_item(discord.ui.Button(label=label, url=url, emoji=emoji, row=0))

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

        await interaction.response.defer(ephemeral=False)
        submission = await db.upsert_recruitment_submission(
            owner.id,
            self.position,
            interaction.channel.id,
            self.gdrive_link.value.strip(),
            self.notes.value.strip() or None,
        )
        try:
            await publish_recruitment_review(interaction.guild, submission, owner)
        except (RuntimeError, discord.HTTPException):
            return await interaction.followup.send(
                "Hasil belum dapat dikirim ke staff-mod. Hubungi administrator dan coba lagi.",
                ephemeral=False,
            )
        await interaction.followup.send(
            embed=discord.Embed(
                title="Hasil Tes Berhasil Dikirim",
                description=(
                    "Hasil tes kamu sudah masuk ke antrean review Administrator.\n"
                    "Tunggu informasi berikutnya di tiket privat ini."
                ),
                color=discord.Color.green(),
            ).set_footer(text=f"Recruitment #{submission['id']} • {self.position}"),
            ephemeral=False,
        )


class RecruitmentApproveDynamic(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"recruitment:approve:(?P<submission_id>\d+):v2",
):
    """Persistent, stateless recruitment approval routed from staff-mod."""

    def __init__(self, submission_id: int):
        self.submission_id = submission_id
        super().__init__(
            discord.ui.Button(
                label="Approve Staff",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"recruitment:approve:{submission_id}:v2",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["submission_id"]))

    async def callback(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "Hanya administrator yang dapat approve.", ephemeral=True
            )
        if not interaction.guild:
            return await interaction.response.send_message("Server tidak ditemukan.", ephemeral=True)
        submission = await db.get_recruitment_submission(self.submission_id)
        if not submission or submission["status"] != "submitted":
            return await interaction.response.send_message(
                "Submission ini sudah diproses atau tidak ditemukan.", ephemeral=True
            )
        applicant = interaction.guild.get_member(int(submission["applicant_id"]))
        if applicant is None:
            try:
                applicant = await interaction.guild.fetch_member(int(submission["applicant_id"]))
            except (discord.NotFound, discord.HTTPException):
                applicant = None
        staff_role = interaction.guild.get_role(ROLE_STAFF_ID)
        if not applicant:
            return await interaction.response.send_message("Pelamar tidak ditemukan di server.", ephemeral=True)
        if not staff_role:
            return await interaction.response.send_message(
                "Role Staff belum dikonfigurasi.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        await applicant.add_roles(
            staff_role,
            reason=f"Lulus rekrutmen posisi {submission['position']}",
        )
        ticket = await find_or_create_staff_ticket(interaction.guild, applicant)
        if not ticket:
            return await interaction.followup.send(
                "Tiket staff tidak dapat dibuat. Periksa kategori dan permission bot.",
                ephemeral=True,
            )
        if not await db.approve_recruitment_submission(self.submission_id, interaction.user.id):
            return await interaction.followup.send(
                "Submission sudah diproses Administrator lain.", ephemeral=True
            )

        approved = build_review_embed(submission, applicant)
        approved.title = f"✅ Rekrutmen Disetujui #{self.submission_id}"
        approved.description = f"Pelamar diterima sebagai staff oleh {interaction.user.mention}."
        approved.color = discord.Color.green()
        if interaction.message:
            await interaction.message.edit(
                embed=approved,
                view=None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        await ticket.send(
            content=applicant.mention,
            embed=discord.Embed(
                title="Selamat, Kamu Diterima!",
                description=f"Kamu diterima sebagai staff posisi **{submission['position']}**.",
                color=discord.Color.green(),
            ),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await upsert_staff_panel(ticket, applicant)
        await interaction.followup.send(
            f"{applicant.display_name} berhasil disetujui dan tiket staff sudah diperbarui.",
            ephemeral=True,
        )


class RecruitmentReviewView(discord.ui.View):
    def __init__(self, submission_id: int):
        super().__init__(timeout=None)
        self.add_item(RecruitmentApproveDynamic(submission_id))


class LegacyRecruitmentReviewView(RecruitmentBaseView):
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
            self.bot.add_view(LegacyRecruitmentReviewView(position))

    async def reconcile_legacy_reviews(self, guild: discord.Guild) -> int:
        return await reconcile_legacy_recruitment_reviews(guild)

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

        @self.bot.tree.command(name="ambil-test", description="Tampilkan kembali bahan tes rekrutmen")
        async def get_recruitment_test_command(interaction: discord.Interaction):
            if not isinstance(interaction.channel, discord.TextChannel):
                return await interaction.response.send_message("Gunakan command ini di tiket rekrutmen.", ephemeral=False)
            owner = get_ticket_owner(interaction.channel)
            position = get_topic_position(interaction.channel)
            if interaction.channel.category_id != REKRUT_CAT_ID or not owner:
                return await interaction.response.send_message("Command ini hanya tersedia di tiket rekrutmen.", ephemeral=False)
            if interaction.user.id != owner.id and not is_admin(interaction.user):
                return await interaction.response.send_message(
                    "Hanya pemilik tiket atau administrator yang dapat mengambil tes.", ephemeral=False
                )
            if position not in POSITIONS:
                return await interaction.response.send_message(
                    "Pilih posisi TL, TS, atau TL+TS terlebih dahulu.", ephemeral=False
                )
            await interaction.response.send_message(
                embed=build_test_embed(position), view=RecruitmentSubmitView(position), ephemeral=False
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

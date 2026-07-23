from datetime import date, datetime

import discord

import database as db
from config import ROLE_STAFF_ID, STAFF_TASKS_CHANNEL_ID
from helpers.utils import (
    calculate_final_rate, find_or_create_staff_ticket, format_currency, get_or_fetch_member,
    is_admin, is_popular_series, normalize_role,
)
from chapter_utils import chapter_display, parse_chapters
from panels.claim_view import ClaimView
from views.ticket_views import TicketSubmitView


class AssignRoleView(discord.ui.View):
    """Wizard: choose role and optionally a staff member, then continue."""

    def __init__(self):
        super().__init__(timeout=180)
        self.role = None
        self.staff_id = None
        self.add_item(AssignRoleSelect(self))
        self.add_item(AssignStaffSelect(self))

    async def interaction_check(self, interaction):
        if is_admin(interaction.user):
            return True
        await interaction.response.send_message("Hanya administrator yang dapat membuat tugas.")
        return False

    @discord.ui.button(label="Lanjut Isi Detail", style=discord.ButtonStyle.primary, row=2)
    async def continue_button(self, interaction, _button):
        if not self.role:
            return await interaction.response.send_message("Pilih role tugas dahulu.")
        await interaction.response.send_modal(AssignModal(self.role, self.staff_id))


class AssignRoleSelect(discord.ui.Select):
    def __init__(self, wizard):
        self.wizard = wizard
        super().__init__(placeholder="1. Pilih role tugas", options=[
            discord.SelectOption(label="TL — Translator", value="TL", description="Menerjemahkan chapter"),
            discord.SelectOption(label="TS — Typesetter", value="TS", description="Cleaning, redraw, typesetting"),
            discord.SelectOption(label="TL+TS — Keduanya", value="TL+TS", description="Dikerjakan satu staf"),
        ], row=0)

    async def callback(self, interaction):
        self.wizard.role = self.values[0]
        await interaction.response.defer()


class AssignStaffSelect(discord.ui.UserSelect):
    def __init__(self, wizard):
        self.wizard = wizard
        super().__init__(placeholder="2. Pilih staf (opsional; kosong = open claim)", min_values=0, max_values=1, row=1)

    async def callback(self, interaction):
        if self.values:
            member = self.values[0]
            if not isinstance(member, discord.Member) or not any(r.id == ROLE_STAFF_ID for r in member.roles):
                return await interaction.response.send_message("Member yang dipilih belum memiliki role Staff.")
            self.wizard.staff_id = member.id
        else:
            self.wizard.staff_id = None
        await interaction.response.defer()


class AssignModal(discord.ui.Modal, title="Detail Tugas Baru"):
    manga = discord.ui.TextInput(label="Judul Manga", placeholder="Contoh: Solo Leveling")
    chapter = discord.ui.TextInput(label="Chapter (Maks. 5)", placeholder="Rentang 1-5 atau daftar 1,3,7,8.5")
    rate_override = discord.ui.TextInput(label="Bayaran per Chapter (Opsional)", placeholder="Contoh: 12000", required=False)
    page_count = discord.ui.TextInput(label="Jumlah Halaman (Opsional)", placeholder="Contoh: 24", required=False)
    deadline = discord.ui.TextInput(label="Deadline (Opsional)", placeholder="YYYY-MM-DD, contoh: 2026-07-25", required=False)

    def __init__(self, role, staff_id=None):
        super().__init__()
        self.selected_role = role
        self.staff_id = staff_id

    async def on_submit(self, interaction):
        role = normalize_role(self.selected_role)
        if not is_admin(interaction.user) or not role:
            return await interaction.response.send_message("Data assign tidak valid.")
        try:
            chapters = parse_chapters(self.chapter.value)
        except ValueError as error:
            return await interaction.response.send_message(str(error))
        base_rate = await db.get_role_payrate(role)
        override = False
        if self.rate_override.value:
            try:
                base_rate = int(self.rate_override.value.replace(".", "").replace(",", "").strip())
                if not 0 <= base_rate <= 1_000_000:
                    raise ValueError
                override = True
            except ValueError:
                return await interaction.response.send_message("Bayaran harus angka antara 0 dan Rp1.000.000.")
        try:
            pages = int(self.page_count.value or 0)
            if not 0 <= pages <= 1000:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("Jumlah halaman harus 0–1000.")
        deadline_at = None
        tight = False
        if self.deadline.value:
            try:
                parsed = datetime.strptime(self.deadline.value.strip(), "%Y-%m-%d").date()
                if parsed < date.today():
                    raise ValueError
                deadline_at = parsed.isoformat()
                tight = (parsed - date.today()).days <= 2
            except ValueError:
                return await interaction.response.send_message("Deadline harus YYYY-MM-DD dan tidak boleh sudah lewat.")
        multiplier = 1.0
        bonuses = []
        if is_popular_series(self.manga.value): multiplier += .3; bonuses.append("Series populer +30%")
        if pages > 20: multiplier += .2; bonuses.append(">20 halaman +20%")
        if tight: multiplier += .1; bonuses.append("Deadline ≤2 hari +10%")
        if override:
            rate_per_chapter, multiplier, bonuses = base_rate, 1.0, ["Bayaran manual per chapter"]
        else:
            rate_per_chapter = calculate_final_rate(base_rate, role, multiplier)
        final_rate = rate_per_chapter * len(chapters)
        payload = dict(manga=self.manga.value.strip(), chapter=chapter_display(chapters), chapters=chapters, role=role,
                       base_rate=base_rate, rate_per_chapter=rate_per_chapter,
                       final_rate=final_rate, multiplier=multiplier,
                       staff_id=self.staff_id, deadline_at=deadline_at, bonuses=bonuses)
        target = f"<@{self.staff_id}> (langsung)" if self.staff_id else "Open claim untuk semua Staff"
        embed = discord.Embed(title="Konfirmasi Tugas", description="Periksa sebelum tugas diterbitkan.", color=discord.Color.gold())
        embed.add_field(name="Manga / Chapter", value=f"{payload['manga']} — Ch. {payload['chapter']}", inline=False)
        embed.add_field(name="Role", value=role)
        embed.add_field(name="Rate / Chapter", value=format_currency(rate_per_chapter))
        embed.add_field(name="Jumlah Chapter", value=str(len(chapters)))
        embed.add_field(name="Total Bayaran", value=format_currency(final_rate))
        embed.add_field(name="Tujuan", value=target, inline=False)
        embed.add_field(name="Deadline", value=deadline_at or "Tidak ditentukan")
        embed.add_field(name="Perhitungan", value=", ".join(bonuses) or "Rate default", inline=False)
        await interaction.response.send_message(embed=embed, view=ConfirmAssignmentView(payload))


class ConfirmAssignmentView(discord.ui.View):
    def __init__(self, payload):
        super().__init__(timeout=180)
        self.payload = payload

    @discord.ui.button(label="Terbitkan Tugas", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, _button):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator yang dapat mengonfirmasi.")
        await interaction.response.defer()
        p = self.payload
        assignment_id = await db.create_assignment(**{k: p[k] for k in ("manga", "chapter", "chapters", "role", "base_rate", "rate_per_chapter", "final_rate", "multiplier", "staff_id", "deadline_at")})
        target_channel = None
        if p["staff_id"]:
            member = await get_or_fetch_member(interaction.guild, p["staff_id"])
            if member:
                target_channel = await find_or_create_staff_ticket(interaction.guild, member)
                if target_channel:
                    await db.set_assignment_ticket_channel(assignment_id, target_channel.id)
                    embed = build_task_embed(assignment_id, p, "Dikerjakan")
                    await target_channel.send(content=member.mention, embed=embed, view=TicketSubmitView(assignment_id))
        else:
            target_channel = interaction.guild.get_channel(STAFF_TASKS_CHANNEL_ID)
            if target_channel:
                embed = build_task_embed(assignment_id, p, "Tersedia")
                role = interaction.guild.get_role(ROLE_STAFF_ID)
                msg = await target_channel.send(content=f"{role.mention if role else '@Staff'} Tugas baru tersedia!", embed=embed, view=ClaimView(assignment_id))
                conn = await db.get_db()
                try:
                    await conn.execute("UPDATE assignments SET message_id=? WHERE id=?", (msg.id, assignment_id)); await conn.commit()
                finally: await conn.close()
        for child in self.children: child.disabled = True
        result = discord.Embed(title="Tugas Berhasil Diterbitkan", description=f"Tugas #{assignment_id} dikirim ke {target_channel.mention if target_channel else 'database (channel tidak ditemukan)' }.", color=discord.Color.green())
        await interaction.edit_original_response(embed=result, view=self)

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, _button):
        if not is_admin(interaction.user): return
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content="Pembuatan tugas dibatalkan.", embed=None, view=self)


def build_task_embed(assignment_id, payload, status):
    embed = discord.Embed(title=f"Tugas #{assignment_id}", description=f"**{payload['manga']}** — Chapter {payload['chapter']}", color=discord.Color.blue())
    embed.add_field(name="Role", value=payload["role"])
    embed.add_field(name="Rate / Chapter", value=format_currency(payload["rate_per_chapter"]))
    embed.add_field(name="Total Bayaran", value=format_currency(payload["final_rate"]))
    embed.add_field(name="Status", value=status)
    embed.add_field(name="Deadline", value=payload["deadline_at"] or "Tidak ditentukan", inline=False)
    embed.set_footer(text="Gunakan tombol di bawah untuk melanjutkan alur tugas.")
    return embed

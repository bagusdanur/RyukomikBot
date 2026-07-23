import discord

import database as db
from helpers.utils import STATUS_EMOJI, format_currency, get_current_period, is_staff
from helpers.panel_content import build_guide_embed, build_staff_panel_embed
from views.select_views import StaffTaskView, SubmitSelectView
from views.raw_views import RawAssignmentView
from views.support_views import TaskSupportView
import payment_service as payments
from views.payment_views import IncomeMenuView


class StaffPanelView(discord.ui.View):
    """Persistent staff panel used inside the staff member's private ticket."""

    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_staff(interaction.user):
            return True
        await interaction.response.send_message(
            "Hanya staff yang dapat menggunakan panel ini.", ephemeral=False
        )
        return False

    @discord.ui.button(label="Tugas Saya", style=discord.ButtonStyle.primary, custom_id="staff_tasks")
    async def tasks_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=False)
        assignments = await db.get_assignments_by_staff(interaction.user.id)
        if not assignments:
            return await interaction.followup.send("Kamu belum memiliki tugas.")

        active = [a for a in assignments if a["status"] in ("claimed", "submitted", "revision")]
        completed = [a for a in assignments if a["status"] in ("approved", "paid")]
        embed = discord.Embed(title="Tugas Saya", color=discord.Color.blue())
        if active:
            embed.add_field(
                name="Sedang Dikerjakan",
                value="\n".join(
                    f"{STATUS_EMOJI.get(a['status'], '-')} **#{a['id']}** {a['manga']} Ch. {a['chapter']} - {a['status']}"
                    for a in active[:10]
                ),
                inline=False,
            )
        if completed:
            embed.add_field(
                name="Selesai",
                value="\n".join(
                    f"{STATUS_EMOJI.get(a['status'], '-')} **#{a['id']}** {a['manga']} Ch. {a['chapter']}"
                    for a in completed[:10]
                ),
                inline=False,
            )
        await interaction.followup.send(embed=embed, view=StaffTaskView(assignments[:25]))

    @discord.ui.button(label="Submit Hasil", style=discord.ButtonStyle.success, custom_id="staff_submit")
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=False)
        assignments = await db.get_assignments_by_staff(interaction.user.id)
        available = [a for a in assignments if a["status"] in ("claimed", "revision")]
        if not available:
            return await interaction.followup.send("Tidak ada tugas yang bisa di-submit saat ini.")

        embed = discord.Embed(
            title="Submit Hasil",
            description="Pilih tugas yang sudah selesai melalui menu di bawah.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed, view=SubmitSelectView(available[:25]))

    @discord.ui.button(label="Penghasilan & Gaji", style=discord.ButtonStyle.secondary, custom_id="staff_income")
    async def income_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=False)
        period = get_current_period()
        stats = await db.get_staff_stats(interaction.user.id, period)
        embed = discord.Embed(
            title="Penghasilan Saya",
            description=f"Periode **{period}**",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Total Tugas", value=str(stats["total"]), inline=True)
        embed.add_field(name="Disetujui", value=format_currency(stats["total_earned"]), inline=True)
        embed.add_field(name="Sudah Dibayar", value=format_currency(stats["total_paid"]), inline=True)
        embed.add_field(name="Menunggu", value=str(stats["pending"]), inline=True)
        methods = await payments.list_methods(interaction.user.id)
        default = next((item for item in methods if item["is_default"]), None)
        payouts = await payments.list_staff_payouts(interaction.user.id)
        active_invoice = next(
            (item for item in payouts if item["status"] in ("awaiting_method", "issued")), None
        )
        embed.add_field(
            name="Tujuan Pembayaran",
            value=(f"{default['provider']} • {default['masked_account'] if default['method_type'] != 'qris' else 'QRIS'}" if default else "Belum diatur"),
            inline=False,
        )
        embed.add_field(
            name="Invoice Aktif",
            value=(
                f"{active_invoice['invoice_number']} • "
                f"{'Menunggu metode pembayaran' if active_invoice['status'] == 'awaiting_method' else 'Menunggu transfer'}"
                if active_invoice else "Tidak ada invoice aktif"
            ),
            inline=False,
        )
        embed.set_footer(text="Jadwal gajian: tanggal 4 dan 19 • Pencairan langsung memerlukan konfirmasi admin.")
        await interaction.followup.send(embed=embed, view=IncomeMenuView())

    @discord.ui.button(label="Download RAW", style=discord.ButtonStyle.primary, custom_id="staff_raw_download", row=1)
    async def raw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        assignments = await db.get_assignments_by_staff(interaction.user.id)
        active = [item for item in assignments if item["status"] in ("claimed", "revision")]
        if not active:
            return await interaction.response.send_message(
                "Kamu belum memiliki tugas aktif. Claim atau terima tugas terlebih dahulu sebelum download RAW."
            )
        embed = discord.Embed(
            title="Download RAW untuk Proyek",
            description="Pilih tugas aktif. Judul komik akan diambil otomatis dari proyek tersebut.",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=RawAssignmentView(active))

    @discord.ui.button(label="Bantuan Tugas", style=discord.ButtonStyle.danger, custom_id="staff_task_support", row=1)
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        assignments = await db.get_assignments_by_staff(interaction.user.id)
        active = [item for item in assignments if item["status"] in ("claimed", "revision", "submitted")]
        if not active:
            return await interaction.response.send_message("Kamu tidak memiliki tugas aktif yang perlu dibantu.")
        embed = discord.Embed(
            title="Butuh Bantuan Tugas?",
            description="Pilih tugas, lalu laporkan kendala atau minta perpanjangan deadline.",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, view=TaskSupportView(active))

    @discord.ui.button(label="Panduan", style=discord.ButtonStyle.secondary, custom_id="staff_guide", row=1)
    async def guide_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=build_guide_embed("staff"), ephemeral=False)

async def upsert_staff_panel(channel: discord.TextChannel, staff: discord.Member):
    """Update and pin the sole staff panel so chat history cannot bury it."""
    embed = build_staff_panel_embed(staff)
    candidates = list(await channel.pins())
    known_ids = {message.id for message in candidates}
    async for message in channel.history(limit=100):
        if message.id not in known_ids:
            candidates.append(message)
    for message in candidates:
        if message.author.id != channel.guild.me.id or not message.embeds:
            continue
        current = message.embeds[0]
        if "Ruang Kerja Staff" in (current.title or "") or "Private Staff Panel" in (current.footer.text or ""):
            await message.edit(embed=embed, view=StaffPanelView())
            if not message.pinned:
                try:
                    await message.pin(reason="Panel staff agar selalu mudah ditemukan")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            return message, False
    message = await channel.send(embed=embed, view=StaffPanelView())
    try:
        await message.pin(reason="Panel staff agar selalu mudah ditemukan")
    except (discord.Forbidden, discord.HTTPException):
        pass
    return message, True

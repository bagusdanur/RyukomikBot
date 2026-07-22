import discord

from helpers.utils import is_admin, format_currency, get_current_period, get_or_fetch_member
from views.select_views import ConfirmPayView
import database as db
from config import ROLE_STAFF_ID


class RekapStaffView(discord.ui.View):
    """Choose a staff member without copying a Discord ID."""

    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(RekapStaffSelect())


class RekapStaffSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Pilih staff yang akan direkap", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator yang dapat membuat rekap.")
        member = self.values[0]
        if not isinstance(member, discord.Member) or not any(role.id == ROLE_STAFF_ID for role in member.roles):
            return await interaction.response.send_message("Member yang dipilih belum memiliki role Staff.")
        await interaction.response.send_modal(RekapModal(member.id))


class RekapModal(discord.ui.Modal, title="Rekap Pembayaran"):
    """Modal for payment recap."""

    function_name = "RekapModal"

    period = discord.ui.TextInput(
        label="Periode",
        placeholder="YYYY-MM (contoh: 2026-07)",
        style=discord.TextStyle.short,
        required=False,
    )

    def __init__(self, staff_id: int):
        super().__init__()
        self.selected_staff_id = staff_id

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "Hanya admin yang bisa menggunakan fitur ini!",
                ephemeral=False,
            )

        period = self.period.value.strip() if self.period.value else get_current_period()
        try:
            parts = period.split("-")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                raise ValueError
            month = int(parts[1])
            if month < 1 or month > 12:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "Format periode harus YYYY-MM, contoh: 2026-07.",
                ephemeral=False,
            )

        staff_id = self.selected_staff_id

        staff = await get_or_fetch_member(interaction.guild, staff_id) if interaction.guild else None

        if not staff:
            return await interaction.response.send_message("Staff tidak ditemukan di server!", ephemeral=False)

        stats = await db.get_staff_stats(staff_id, period)
        assignments = await db.get_approved_assignments_for_payment(staff_id, period)
        total_amount = sum(a["final_rate"] for a in assignments)

        if not assignments:
            return await interaction.response.send_message(
                f"Tidak ada tugas approved yang belum dibayar untuk **{staff.display_name}** "
                f"di periode **{period}**.",
                ephemeral=False,
            )

        embed = discord.Embed(
            title="Rekap Pembayaran",
            description=f"**{staff.display_name}** - Periode {period}",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Ringkasan",
            value=(
                f"Total Tugas Periode: {stats['total']}\n"
                f"Siap Dibayar: {len(assignments)}\n"
                f"Total: {format_currency(total_amount)}"
            ),
            inline=False,
        )

        detail_text = ""
        for assignment in assignments[:20]:
            detail_text += (
                f"- {assignment['manga']} Ch.{assignment['chapter']}: "
                f"{format_currency(assignment['final_rate'])}\n"
            )

        if len(assignments) > 20:
            detail_text += f"...dan {len(assignments) - 20} tugas lainnya."

        embed.add_field(name="Detail Tugas", value=detail_text, inline=False)

        await interaction.response.send_message(
            embed=embed,
            view=ConfirmPayView(
                staff_id=staff_id,
                period=period,
                total=total_amount,
                count=len(assignments),
            ),
            ephemeral=False,
        )

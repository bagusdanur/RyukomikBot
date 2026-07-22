import discord

import database as db
from helpers.utils import STATUS_EMOJI, format_currency, get_current_period, is_staff
from views.select_views import SubmitSelectView


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
        await interaction.followup.send(embed=embed)

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

    @discord.ui.button(label="Penghasilan", style=discord.ButtonStyle.secondary, custom_id="staff_income")
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
        await interaction.followup.send(embed=embed)

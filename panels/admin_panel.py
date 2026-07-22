import discord

import database as db
from helpers.utils import STATUS_EMOJI, format_currency, is_admin
from helpers.panel_content import build_guide_embed
from views.select_views import ReviewSelectView


class AdminPanelView(discord.ui.View):
    """Persistent admin panel used only in the staff moderation channel."""

    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_admin(interaction.user):
            return True
        await interaction.response.send_message(
            "Hanya administrator yang dapat menggunakan panel ini.", ephemeral=False
        )
        return False

    @discord.ui.button(label="Assign Tugas", style=discord.ButtonStyle.primary, custom_id="admin_assign")
    async def assign_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from modals.assign_modal import AssignRoleView

        embed = discord.Embed(
            title="Langkah 1 • Pilih Role Tugas",
            description=(
                "Pilih role yang dibutuhkan. Setelah itu form detail tugas akan terbuka.\n\n"
                "• **TL** untuk translator\n"
                "• **TS** untuk typesetter/editor\n"
                "• **TL+TS** untuk satu staff yang mengerjakan keduanya"
            ),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=AssignRoleView(), ephemeral=False)

    @discord.ui.button(label="Review", style=discord.ButtonStyle.secondary, custom_id="admin_review")
    async def review_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=False)
        submitted = await db.get_assignments_by_status("submitted")
        if not submitted:
            return await interaction.followup.send("Tidak ada tugas yang menunggu review.")

        embed = discord.Embed(
            title="Review Tugas",
            description="Pilih tugas melalui menu di bawah untuk melihat hasil dan memprosesnya.",
            color=discord.Color.blue(),
        )
        for assignment in submitted[:10]:
            embed.add_field(
                name=f"#{assignment['id']} - {assignment['manga']}",
                value=(
                    f"Chapter: **{assignment['chapter']}** | Role: **{assignment['role']}**\n"
                    f"Status: **{assignment['status']}**"
                ),
                inline=False,
            )
        await interaction.followup.send(embed=embed, view=ReviewSelectView(submitted[:25]))

    @discord.ui.button(label="Rekap Gaji", style=discord.ButtonStyle.success, custom_id="admin_rekap")
    async def rekap_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from modals.rekap_modal import RekapStaffView

        embed = discord.Embed(title="Rekap Gaji", description="Pilih staff. Setelah itu isi periode pembayaran; kamu tidak perlu menyalin Discord ID.", color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, view=RekapStaffView())

    @discord.ui.button(label="Stats", style=discord.ButtonStyle.danger, custom_id="admin_stats")
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=False)
        connection = await db.get_db()
        try:
            cursor = await connection.execute(
                "SELECT status, COUNT(*) FROM assignments GROUP BY status"
            )
            status_counts = dict(await cursor.fetchall())
            cursor = await connection.execute(
                "SELECT COALESCE(SUM(final_rate), 0) FROM assignments "
                "WHERE status IN ('approved', 'paid')"
            )
            total_earnings = (await cursor.fetchone())[0]
            cursor = await connection.execute(
                "SELECT COALESCE(SUM(final_rate), 0) FROM assignments "
                "WHERE status IN ('claimed', 'submitted', 'revision')"
            )
            pending_earnings = (await cursor.fetchone())[0]
        finally:
            await connection.close()

        status_text = "\n".join(
            f"{STATUS_EMOJI.get(status, '-')} {status.title()}: **{status_counts.get(status, 0)}**"
            for status in ("open", "claimed", "submitted", "revision", "approved", "paid")
        )
        embed = discord.Embed(title="Statistik Staff", color=discord.Color.gold())
        embed.add_field(name="Status Tugas", value=status_text or "Belum ada data.", inline=False)
        embed.add_field(name="Sudah Disetujui", value=format_currency(total_earnings), inline=True)
        embed.add_field(name="Sedang Diproses", value=format_currency(pending_earnings), inline=True)
        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="Panduan", emoji="📚", style=discord.ButtonStyle.secondary, custom_id="admin_guide")
    async def guide_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=build_guide_embed("admin"), ephemeral=False)

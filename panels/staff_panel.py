import discord
from helpers.utils import is_staff, STATUS_EMOJI, format_currency, get_current_period
from views.ticket_views import TicketSubmitModal
import database as db


class StaffPanelView(discord.ui.View):
    """Staff panel with 3 buttons: Tugas Saya, Submit Hasil, Penghasilan."""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📋 Tugas Saya", style=discord.ButtonStyle.primary, custom_id="staff_tasks")
    async def tasks_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show staff's current tasks."""
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya staff yang bisa menggunakan fitur ini!",
                ephemeral=False
            )
        
        await interaction.response.defer(ephemeral=False)
        
        assignments = await db.get_assignments_by_staff(interaction.user.id)
        
        if not assignments:
            return await interaction.followup.send(
                "📋 Kamu belum memiliki tugas.",
                ephemeral=False
            )
        
        embed = discord.Embed(
            title="📋 Tugas Saya",
            color=discord.Color.blue()
        )
        
        # Group by status
        active = [a for a in assignments if a["status"] in ("claimed", "submitted", "revision")]
        completed = [a for a in assignments if a["status"] in ("approved", "paid")]
        
        if active:
            active_text = ""
            for a in active[:5]:
                emoji = STATUS_EMOJI[a["status"]]
                active_text += (
                    f"{emoji} **#{a['id']}** - {a['manga']} Ch.{a['chapter']}\n"
                    f"   Role: {a['role']} | Status: {a['status']}\n"
                )
            embed.add_field(name="Aktif", value=active_text, inline=False)
        
        if completed:
            completed_text = ""
            for a in completed[:5]:
                emoji = STATUS_EMOJI[a["status"]]
                completed_text += f"{emoji} **#{a['id']}** - {a['manga']} Ch.{a['chapter']}\n"
            embed.add_field(name="Selesai", value=completed_text, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=False)
    
    @discord.ui.button(label="📤 Submit Hasil", style=discord.ButtonStyle.success, custom_id="staff_submit")
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show claimed tasks for submission."""
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya staff yang bisa menggunakan fitur ini!",
                ephemeral=False
            )
        
        await interaction.response.defer(ephemeral=False)
        
        assignments = await db.get_assignments_by_staff(interaction.user.id)
        claimed = [a for a in assignments if a["status"] in ("claimed", "revision")]
        
        if not claimed:
            return await interaction.followup.send(
                "📤 Tidak ada tugas yang bisa di-submit saat ini.",
                ephemeral=False
            )
        
        embed = discord.Embed(
            title="📤 Submit Hasil",
            description="Pilih tugas yang ingin di-submit:",
            color=discord.Color.green()
        )
        
        for a in claimed:
            embed.add_field(
                name=f"#{a['id']} - {a['manga']}",
                value=f"Chapter: {a['chapter']} | Role: {a['role']}",
                inline=False
            )
        
        await interaction.followup.send(
            embed=embed,
            view=SubmitSelectView(claimed),
            ephemeral=False
        )
    
    @discord.ui.button(label="💰 Penghasilan", style=discord.ButtonStyle.secondary, custom_id="staff_income")
    async def income_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show staff earnings."""
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya staff yang bisa menggunakan fitur ini!",
                ephemeral=False
            )
        
        await interaction.response.defer(ephemeral=False)
        
        period = get_current_period()
        stats = await db.get_staff_stats(interaction.user.id, period)
        
        embed = discord.Embed(
            title="💰 Penghasilan Saya",
            description=f"Periode: {period}",
            color=discord.Color.gold()
        )
        
        embed.add_field(
            name="Ringkasan",
            value=(
                f"📊 Total Tugas: {stats['total']}\n"
                f"✅ Diterima: {format_currency(stats['total_earned'])}\n"
                f"💰 Sudah Dibayar: {format_currency(stats['total_paid'])}\n"
                f"⏳ Pending: {stats['pending']}"
            ),
            inline=False
        )
        
        # Get detailed assignments
        assignments = await db.get_assignments_by_staff(interaction.user.id)
        approved = [a for a in assignments if a["status"] == "approved"]
        
        if approved:
            detail_text = ""
            for a in approved[:5]:
                detail_text += f"• {a['manga']} Ch.{a['chapter']}: {format_currency(a['final_rate'])}\n"
            embed.add_field(name="Detail (Belum Dibayar)", value=detail_text, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=False)


class SubmitSelectView(discord.ui.View):
    """Dropdown for staff to select assignment to submit."""
    
    def __init__(self, assignments: list):
        super().__init__(timeout=120)
        self.add_item(SubmitSelect(assignments))


class SubmitSelect(discord.ui.Select):
    """Dropdown to select assignment for submission."""
    
    def __init__(self, assignments: list):
        options = []
        for a in assignments:
            options.append(
                discord.SelectOption(
                    label=f"#{a['id']} - {a['manga']}",
                    description=f"Ch {a['chapter']} | {a['role']}",
                    value=str(a["id"])
                )
            )
        
        super().__init__(
            placeholder="Pilih tugas untuk di-submit...",
            options=options[:25],
            custom_id="submit_select"
        )
    
    async def callback(self, interaction: discord.Interaction):
        assignment_id = int(self.values[0])
        assignment = await db.get_assignment(assignment_id)
        
        if not assignment:
            return await interaction.response.send_message(
                "❌ Tugas tidak ditemukan!",
                ephemeral=False
            )
        
        if assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message(
                "Kamu hanya bisa submit tugas milikmu sendiri!",
                ephemeral=False
            )
        
        if assignment["status"] not in ("claimed", "revision"):
            return await interaction.response.send_message(
                "Tugas ini belum bisa di-submit!",
                ephemeral=False
            )
        
        modal = TicketSubmitModal(assignment)
        await interaction.response.send_modal(modal)

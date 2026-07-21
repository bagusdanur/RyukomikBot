import discord
from discord.ext import commands
from helpers.utils import is_admin, STATUS_EMOJI, format_currency, get_current_period
import database as db


class AdminPanelView(discord.ui.View):
    """Admin panel with 4 buttons: Assign, Review, Rekap, Stats."""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📋 Assign Tugas", style=discord.ButtonStyle.primary, custom_id="admin_assign")
    async def assign_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open assign modal."""
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa menggunakan fitur ini!",
                ephemeral=True
            )
        
        from modals.assign_modal import AssignModal
        modal = AssignModal()
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="📝 Review", style=discord.ButtonStyle.secondary, custom_id="admin_review")
    async def review_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show submitted assignments for review."""
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa menggunakan fitur ini!",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        submitted = await db.get_assignments_by_status("submitted")
        if not submitted:
            return await interaction.followup.send(
                "📋 Tidak ada tugas yang perlu di-review.",
                ephemeral=True
            )
        
        embed = discord.Embed(
            title="📝 Review Tugas",
            description="Berikut adalah tugas yang perlu di-review:",
            color=discord.Color.blue()
        )
        
        for assignment in submitted[:10]:
            staff = interaction.guild.get_member(assignment["staff_id"])
            staff_name = staff.display_name if staff else f"ID: {assignment['staff_id']}"
            
            embed.add_field(
                name=f"{STATUS_EMOJI[assignment['status']]} #{assignment['id']} - {assignment['manga']}",
                value=(
                    f"**Chapter:** {assignment['chapter']}\n"
                    f"**Role:** {assignment['role']}\n"
                    f"**Staff:** {staff_name}\n"
                    f"**Link:** {assignment['gdrive_link'] or 'Belum ada'}"
                ),
                inline=False
            )
        
        await interaction.followup.send(embed=embed, view=ReviewSelectView(submitted[:10]), ephemeral=True)
    
    @discord.ui.button(label="📊 Rekap", style=discord.ButtonStyle.success, custom_id="admin_rekap")
    async def rekap_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open rekap modal."""
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa menggunakan fitur ini!",
                ephemeral=True
            )
        
        from modals.rekap_modal import RekapModal
        modal = RekapModal()
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="📈 Stats", style=discord.ButtonStyle.danger, custom_id="admin_stats")
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show overall statistics."""
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa menggunakan fitur ini!",
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        # Get stats from database
        db_conn = await db.get_db()
        try:
            # Count by status
            cursor = await db_conn.execute("""
                SELECT status, COUNT(*) as count 
                FROM assignments 
                GROUP BY status
            """)
            status_counts = {row[0]: row[1] for row in await cursor.fetchall()}
            
            # Total earnings
            cursor = await db_conn.execute("""
                SELECT SUM(final_rate) 
                FROM assignments 
                WHERE status IN ('approved', 'paid')
            """)
            total_earnings = (await cursor.fetchone())[0] or 0
            
            # Pending earnings
            cursor = await db_conn.execute("""
                SELECT SUM(final_rate) 
                FROM assignments 
                WHERE status IN ('submitted', 'claimed')
            """)
            pending_earnings = (await cursor.fetchone())[0] or 0
            
        finally:
            await db_conn.close()
        
        embed = discord.Embed(
            title="📈 Statistik Ryukomik",
            color=discord.Color.gold()
        )
        
        # Status breakdown
        status_text = ""
        for status, emoji in STATUS_EMOJI.items():
            count = status_counts.get(status, 0)
            status_text += f"{emoji} {status.title()}: {count}\n"
        
        embed.add_field(name="Status Tugas", value=status_text, inline=True)
        
        # Earnings
        embed.add_field(
            name="Pendapatan",
            value=(
                f"✅ Total Diterima: {format_currency(total_earnings)}\n"
                f"⏳ Pending: {format_currency(pending_earnings)}"
            ),
            inline=True
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)


class ReviewSelectView(discord.ui.View):
    """Dropdown for admin to select assignments to review."""
    
    def __init__(self, assignments: list):
        super().__init__(timeout=120)
        self.add_item(ReviewSelect(assignments))


class ReviewSelect(discord.ui.Select):
    """Dropdown to select assignment for review."""
    
    def __init__(self, assignments: list):
        options = []
        for a in assignments:
            staff_id = a["staff_id"]
            options.append(
                discord.SelectOption(
                    label=f"#{a['id']} - {a['manga']}",
                    description=f"Ch {a['chapter']} | {a['role']}",
                    value=str(a["id"])
                )
            )
        
        super().__init__(
            placeholder="Pilih tugas untuk di-review...",
            options=options[:25],  # Discord max options
            custom_id="review_select"
        )
    
    async def callback(self, interaction: discord.Interaction):
        assignment_id = int(self.values[0])
        assignment = await db.get_assignment(assignment_id)
        
        if not assignment:
            return await interaction.response.send_message(
                "❌ Tugas tidak ditemukan!",
                ephemeral=True
            )
        
        embed = discord.Embed(
            title=f"📝 Review Tugas #{assignment['id']}",
            description=f"**{assignment['manga']}** - Chapter {assignment['chapter']}",
            color=discord.Color.blue()
        )
        
        staff = interaction.guild.get_member(assignment["staff_id"])
        staff_name = staff.display_name if staff else f"ID: {assignment['staff_id']}"
        
        embed.add_field(name="Staff", value=staff_name, inline=True)
        embed.add_field(name="Role", value=assignment["role"], inline=True)
        embed.add_field(name="Rate", value=format_currency(assignment["final_rate"]), inline=True)
        embed.add_field(name="Link GDrive", value=assignment["gdrive_link"] or "Belum ada", inline=False)
        
        if assignment["admin_notes"]:
            embed.add_field(name="Catatan", value=assignment["admin_notes"], inline=False)
        
        await interaction.response.send_message(
            embed=embed,
            view=TicketReviewView(assignment["id"]),
            ephemeral=True
        )


class TicketReviewView(discord.ui.View):
    """Review buttons: Approve + Revise."""
    
    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id
    
    @discord.ui.button(label="✅ Setuju", style=discord.ButtonStyle.success, custom_id="review_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Approve assignment."""
        success = await db.approve_assignment(self.assignment_id)
        
        if success:
            assignment = await db.get_assignment(self.assignment_id)
            staff = interaction.guild.get_member(assignment["staff_id"])
            
            embed = discord.Embed(
                title="✅ Tugas Disetujui",
                description=f"Tugas #{self.assignment_id} telah disetujui!",
                color=discord.Color.green()
            )
            embed.add_field(name="Manga", value=assignment["manga"], inline=True)
            embed.add_field(name="Chapter", value=assignment["chapter"], inline=True)
            embed.add_field(name="Staff", value=staff.display_name if staff else "Unknown", inline=True)
            
            await interaction.response.edit_message(embed=embed, view=None)
            
            # Notify staff
            if staff:
                try:
                    await staff.send(f"✅ Tugas kamu untuk **{assignment['manga']}** chapter **{assignment['chapter']}** telah disetujui!")
                except:
                    pass
        else:
            await interaction.response.send_message(
                "❌ Gagal menyetujui tugas!",
                ephemeral=True
            )
    
    @discord.ui.button(label="🔄 Revisi", style=discord.ButtonStyle.danger, custom_id="review_revise")
    async def revise_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open revise modal."""
        modal = ReviseModal(self.assignment_id)
        await interaction.response.send_modal(modal)


class ReviseModal(discord.ui.Modal, title="Revisi Tugas"):
    """Modal for revising assignment."""
    
    def __init__(self, assignment_id: int):
        super().__init__()
        self.assignment_id = assignment_id
    
    catatan = discord.ui.TextInput(
        label="Catatan Revisi",
        placeholder="Jelaskan apa yang perlu diperbaiki...",
        style=discord.TextStyle.paragraph,
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        success = await db.revise_assignment(self.assignment_id, self.catatan.value)
        
        if success:
            assignment = await db.get_assignment(self.assignment_id)
            staff = interaction.guild.get_member(assignment["staff_id"])
            
            embed = discord.Embed(
                title="🔄 Tugas Direvisi",
                description=f"Tugas #{self.assignment_id} dikembalikan untuk revisi.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Catatan", value=self.catatan.value, inline=False)
            
            await interaction.response.edit_message(embed=embed, view=None)
            
            # Notify staff
            if staff:
                try:
                    await staff.send(
                        f"🔄 Tugas kamu untuk **{assignment['manga']}** chapter **{assignment['chapter']}** perlu revisi.\n"
                        f"**Catatan:** {self.catatan.value}"
                    )
                except:
                    pass
        else:
            await interaction.response.send_message(
                "❌ Gagal merevisi tugas!",
                ephemeral=True
            )

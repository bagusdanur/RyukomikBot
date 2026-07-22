import discord
from helpers.utils import is_admin, format_currency
from views.ticket_views import TicketReviewView, TicketSubmitModal
import database as db


class StaffTaskView(discord.ui.View):
    def __init__(self, assignments: list):
        super().__init__(timeout=300)
        self.add_item(StaffTaskSelect(assignments[:25]))


class StaffTaskSelect(discord.ui.Select):
    def __init__(self, assignments):
        options = [discord.SelectOption(label=f"#{a['id']} {a['manga']}"[:100], value=str(a["id"]), description=f"Ch. {a['chapter']} • {a['status']} • {a['role']}"[:100]) for a in assignments]
        super().__init__(placeholder="Buka detail tugas", options=options)

    async def callback(self, interaction):
        assignment = await db.get_assignment(int(self.values[0]))
        if not assignment or assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message("Tugas ini bukan milikmu.")
        embed = discord.Embed(title=f"Tugas #{assignment['id']}", description=f"**{assignment['manga']}** — Chapter {assignment['chapter']}", color=discord.Color.blue())
        embed.add_field(name="Status", value=assignment["status"]); embed.add_field(name="Role", value=assignment["role"]); embed.add_field(name="Bayaran", value=format_currency(assignment["final_rate"]))
        embed.add_field(name="Deadline", value=assignment.get("deadline_at") or "Tidak ditentukan", inline=False)
        from views.ticket_views import TicketSubmitView
        view = TicketSubmitView(assignment["id"]) if assignment["status"] in ("claimed", "revision") else None
        if view:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)


class ReviewSelectView(discord.ui.View):
    """Dropdown view for admin review selection."""
    
    function_name = "ReviewSelectView"
    
    def __init__(self, assignments: list):
        super().__init__(timeout=120)
        self.add_item(ReviewSelect(assignments))


class ReviewSelect(discord.ui.Select):
    """Dropdown to select assignment for review."""
    
    function_name = "ReviewSelect"
    
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
            placeholder="Pilih tugas untuk di-review...",
            options=options[:25],
            custom_id="review_select"
        )
    
    async def callback(self, interaction: discord.Interaction):
        assignment_id = int(self.values[0])
        assignment = await db.get_assignment(assignment_id)
        
        if not assignment:
            return await interaction.response.send_message(
                "❌ Tugas tidak ditemukan!",
                ephemeral=False
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
            ephemeral=False
        )


class SubmitSelectView(discord.ui.View):
    """Dropdown view for staff submission selection."""
    
    function_name = "SubmitSelectView"
    
    def __init__(self, assignments: list):
        super().__init__(timeout=120)
        self.add_item(SubmitSelect(assignments))


class SubmitSelect(discord.ui.Select):
    """Dropdown to select assignment for submission."""
    
    function_name = "SubmitSelect"
    
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


class ConfirmPayView(discord.ui.View):
    """View for confirming payment."""
    
    function_name = "ConfirmPayView"
    
    def __init__(self, staff_id: int, period: str, total: int, count: int):
        super().__init__(timeout=300)
        self.staff_id = staff_id
        self.period = period
        self.total = total
        self.count = count
    
    @discord.ui.button(label="💰 Bayar Sekarang", style=discord.ButtonStyle.success, custom_id="confirm_pay")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm and process payment."""
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa memproses pembayaran!",
                ephemeral=False
            )
        
        await interaction.response.defer(ephemeral=False)
        
        # Get approved assignments for this staff and period
        db_conn = await db.get_db()
        try:
            cursor = await db_conn.execute("""
                SELECT id, final_rate FROM assignments 
                WHERE staff_id = ? AND approved_at LIKE ? AND status = 'approved'
            """, (self.staff_id, f"{self.period}%"))
            rows = await cursor.fetchall()
            assignment_ids = [row[0] for row in rows]
            total = sum(row[1] for row in rows)
            count = len(rows)
        finally:
            await db_conn.close()
        
        if not assignment_ids:
            return await interaction.followup.send(
                "❌ Tidak ada tugas yang perlu dibayar!",
                ephemeral=False
            )
        
        # Mark as paid
        success = await db.mark_paid(assignment_ids, self.period)
        
        if success:
            # Create payment record
            payment_id = await db.create_payment(
                self.staff_id,
                self.period,
                total,
                count
            )
            
            # Mark payment as paid
            await db.mark_payment_paid(payment_id)
            
            staff = interaction.guild.get_member(self.staff_id)
            staff_name = staff.display_name if staff else f"ID: {self.staff_id}"
            
            embed = discord.Embed(
                title="✅ Pembayaran Berhasil",
                description=f"Pembayaran untuk **{staff_name}** telah diproses!",
                color=discord.Color.green()
            )
            embed.add_field(name="Periode", value=self.period, inline=True)
            embed.add_field(name="Total", value=format_currency(total), inline=True)
            embed.add_field(name="Jumlah Chapter", value=str(count), inline=True)
            
            # Disable button
            for child in self.children:
                child.disabled = True
            
            await interaction.followup.edit_message(
                interaction.message.id,
                embed=embed,
                view=self
            )
            
            # Notify staff
            if staff:
                try:
                    await staff.send(
                        f"💰 Pembayaran kamu untuk periode **{self.period}** telah diproses!\n"
                        f"Total: **{format_currency(total)}**"
                    )
                except:
                    pass
        else:
            await interaction.followup.send(
                "❌ Gagal memproses pembayaran!",
                ephemeral=False
            )

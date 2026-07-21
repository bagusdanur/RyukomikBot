import discord
from helpers.utils import is_admin, STATUS_EMOJI, format_currency
import database as db


class TicketSubmitView(discord.ui.View):
    """View for submitting work in ticket."""
    
    function_name = "TicketSubmitView"
    
    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id
    
    @discord.ui.button(label="📤 Submit Hasil", style=discord.ButtonStyle.success, custom_id="ticket_submit")
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open submit modal."""
        assignment = await db.get_assignment(self.assignment_id)
        
        if not assignment:
            return await interaction.response.send_message(
                "❌ Tugas tidak ditemukan!",
                ephemeral=True
            )
        
        if assignment["status"] != "claimed":
            return await interaction.response.send_message(
                "❌ Tugas ini belum bisa di-submit!",
                ephemeral=True
            )
        
        modal = TicketSubmitModal(assignment)
        await interaction.response.send_modal(modal)


class TicketSubmitModal(discord.ui.Modal, title="Submit Hasil Kerja"):
    """Modal for submitting work."""
    
    function_name = "TicketSubmitModal"
    
    def __init__(self, assignment: dict):
        super().__init__()
        self.assignment = assignment
    
    gdrive_link = discord.ui.TextInput(
        label="Link Google Drive",
        placeholder="https://drive.google.com/...",
        style=discord.TextStyle.short,
        required=True
    )
    
    catatan = discord.ui.TextInput(
        label="Catatan (Opsional)",
        placeholder="Catatan untuk admin...",
        style=discord.TextStyle.paragraph,
        required=False
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        success = await db.submit_assignment(
            self.assignment["id"],
            self.gdrive_link.value,
            self.catatan.value or None
        )
        
        if success:
            embed = discord.Embed(
                title="📤 Hasil Di-submit",
                description="Tugas kamu telah di-submit untuk review!",
                color=discord.Color.green()
            )
            embed.add_field(name="Manga", value=self.assignment["manga"], inline=True)
            embed.add_field(name="Chapter", value=self.assignment["chapter"], inline=True)
            embed.add_field(name="Link", value=self.gdrive_link.value, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Notify in channel
            channel = interaction.channel
            if channel:
                await channel.send(
                    f"📤 **{interaction.user.display_name}** telah submit hasil untuk "
                    f"**{self.assignment['manga']}** chapter **{self.assignment['chapter']}**"
                )
        else:
            await interaction.response.send_message(
                "❌ Gagal submit hasil!",
                ephemeral=True
            )


class TicketReviewView(discord.ui.View):
    """View for admin to review ticket submission."""
    
    function_name = "TicketReviewView"
    
    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id
    
    @discord.ui.button(label="✅ Setuju", style=discord.ButtonStyle.success, custom_id="ticket_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Approve assignment."""
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa approve!",
                ephemeral=True
            )
        
        success = await db.approve_assignment(self.assignment_id)
        
        if success:
            assignment = await db.get_assignment(self.assignment_id)
            staff = interaction.guild.get_member(assignment["staff_id"])
            
            embed = discord.Embed(
                title="✅ Tugas Disetujui",
                description=f"Chapter **{assignment['manga']}** telah disetujui!",
                color=discord.Color.green()
            )
            
            # Disable buttons
            for child in self.children:
                child.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            # Notify staff
            if staff:
                try:
                    await staff.send(f"✅ Tugas kamu untuk **{assignment['manga']}** chapter **{assignment['chapter']}** telah disetujui!")
                except:
                    pass
            
            # Log
            log_channel = interaction.guild.get_channel(1524468717591859234)
            if log_channel:
                await log_channel.send(
                    f"✅ **{interaction.user.display_name}** telah approve tugas: "
                    f"**{assignment['manga']}** chapter **{assignment['chapter']}**"
                )
        else:
            await interaction.response.send_message(
                "❌ Gagal approve tugas!",
                ephemeral=True
            )
    
    @discord.ui.button(label="🔄 Revisi", style=discord.ButtonStyle.danger, custom_id="ticket_revise")
    async def revise_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open revise modal."""
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa merevisi!",
                ephemeral=True
            )
        
        modal = TicketReviseModal(self.assignment_id)
        await interaction.response.send_modal(modal)


class TicketReviseModal(discord.ui.Modal, title="Revisi Tugas"):
    """Modal for revising ticket assignment."""
    
    function_name = "TicketReviseModal"
    
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
                title="🔄 Perlu Revisi",
                description=f"Chapter **{assignment['manga']}** perlu revisi.",
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

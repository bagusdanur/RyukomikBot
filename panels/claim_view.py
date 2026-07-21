import discord
from helpers.utils import is_staff, STATUS_EMOJI, format_currency
import database as db


class ClaimView(discord.ui.View):
    """View for claiming an assignment."""
    
    def __init__(self, assignment_id: int):
        super().__init__(timeout=None)
        self.assignment_id = assignment_id
    
    @discord.ui.button(label="🎯 Claim Tugas", style=discord.ButtonStyle.primary, custom_id="claim_task")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Claim the assignment."""
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya staff yang bisa claim tugas!",
                ephemeral=True
            )
        
        assignment = await db.get_assignment(self.assignment_id)
        
        if not assignment:
            return await interaction.response.send_message(
                "❌ Tugas tidak ditemukan!",
                ephemeral=True
            )
        
        if assignment["status"] != "open":
            return await interaction.response.send_message(
                "❌ Tugas ini sudah di-claim atau tidak tersedia!",
                ephemeral=True
            )
        
        # Check if staff already has this task
        if assignment["staff_id"] == interaction.user.id:
            return await interaction.response.send_message(
                "❌ Kamu sudah claim tugas ini!",
                ephemeral=True
            )
        
        success = await db.claim_assignment(self.assignment_id, interaction.user.id)
        
        if success:
            embed = discord.Embed(
                title="⏳ Tugas Di-claim",
                description=f"Kamu telah claim tugas ini!",
                color=discord.Color.orange()
            )
            embed.add_field(name="Manga", value=assignment["manga"], inline=True)
            embed.add_field(name="Chapter", value=assignment["chapter"], inline=True)
            embed.add_field(name="Role", value=assignment["role"], inline=True)
            embed.add_field(name="Rate", value=format_currency(assignment["final_rate"]), inline=True)
            
            # Disable the button
            for child in self.children:
                child.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            # Notify in log channel
            log_channel = interaction.guild.get_channel(1524468717591859234)
            if log_channel:
                await log_channel.send(
                    f"📌 **{interaction.user.display_name}** telah claim tugas: "
                    f"**{assignment['manga']}** chapter **{assignment['chapter']}** ({assignment['role']})"
                )
        else:
            await interaction.response.send_message(
                "❌ Gagal claim tugas. Mungkin sudah di-claim orang lain!",
                ephemeral=True
            )

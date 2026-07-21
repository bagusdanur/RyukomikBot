import discord
from helpers.utils import is_admin
import database as db


class RevisiModal(discord.ui.Modal, title="Revisi Tugas"):
    """Modal for revising assignment."""
    
    function_name = "RevisiModal"
    
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
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa merevisi!",
                ephemeral=False
            )
        
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
                ephemeral=False
            )

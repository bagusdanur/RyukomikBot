import discord
from helpers.utils import is_staff, format_currency
import database as db


class SubmitModal(discord.ui.Modal, title="Submit Hasil Kerja"):
    """Modal for submitting work results."""
    
    function_name = "SubmitModal"
    
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
        if not is_staff(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya staff yang bisa submit tugas!",
                ephemeral=True
            )
        
        # Validate assignment
        if self.assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message(
                "❌ Tugas ini bukan milik kamu!",
                ephemeral=True
            )
        
        if self.assignment["status"] != "claimed":
            return await interaction.response.send_message(
                "❌ Tugas ini belum bisa di-submit!",
                ephemeral=True
            )
        
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
            
            # Notify in channel if exists
            if interaction.channel:
                await interaction.channel.send(
                    f"📤 **{interaction.user.display_name}** telah submit hasil untuk "
                    f"**{self.assignment['manga']}** chapter **{self.assignment['chapter']}**"
                )
        else:
            await interaction.response.send_message(
                "❌ Gagal submit hasil!",
                ephemeral=True
            )

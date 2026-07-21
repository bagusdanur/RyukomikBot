import discord
from helpers.utils import is_admin, calculate_rate, get_current_period, format_currency
from config import STAFF_TASKS_CHANNEL_ID, ROLE_STAFF_ID
from panels.claim_view import ClaimView
import database as db


class AssignModal(discord.ui.Modal, title="Assign Tugas Baru"):
    """Modal for assigning new tasks."""
    
    function_name = "AssignModal"
    
    manga = discord.ui.TextInput(
        label="Judul Manga",
        placeholder="Contoh: Solo Leveling",
        style=discord.TextStyle.short,
        required=True
    )
    
    chapter = discord.ui.TextInput(
        label="Chapter",
        placeholder="Contoh: 100",
        style=discord.TextStyle.short,
        required=True
    )
    
    role = discord.ui.TextInput(
        label="Role (TL/PR/CL)",
        placeholder="TL, PR, atau CL",
        style=discord.TextStyle.short,
        required=True
    )
    
    rate_override = discord.ui.TextInput(
        label="Rate Override (Opsional)",
        placeholder="Kosongkan untuk rate default",
        style=discord.TextStyle.short,
        required=False
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa assign tugas!",
                ephemeral=True
            )
        
        # Validate role
        role = self.role.value.upper()
        if role not in ("TL", "PR", "CL"):
            return await interaction.response.send_message(
                "❌ Role harus TL, PR, atau CL!",
                ephemeral=True
            )
        
        # Calculate rate
        base_rate = calculate_rate(role, self.manga.value)
        
        # Apply override if provided
        if self.rate_override.value:
            try:
                override = int(self.rate_override.value)
                if override < 0 or override > 50000:
                    return await interaction.response.send_message(
                        "❌ Rate override harus antara 0 dan 50000!",
                        ephemeral=True
                    )
                base_rate = override
            except ValueError:
                return await interaction.response.send_message(
                    "❌ Rate override harus berupa angka!",
                    ephemeral=True
                )
        
        # Calculate multiplier based on popular series
        from helpers.utils import POPULAR_SERIES
        multiplier = 1.3 if self.manga.value in POPULAR_SERIES else 1.0
        final_rate = int(base_rate * multiplier)
        
        # Get staff role for mention
        staff_role = interaction.guild.get_role(ROLE_STAFF_ID)
        
        # Create assignment in database
        assignment_id = await db.create_assignment(
            manga=self.manga.value,
            chapter=self.chapter.value,
            role=role,
            base_rate=base_rate,
            final_rate=final_rate,
            multiplier=multiplier
        )
        
        # Send to tasks channel
        tasks_channel = interaction.guild.get_channel(STAFF_TASKS_CHANNEL_ID)
        if tasks_channel:
            embed = discord.Embed(
                title="📋 Tugas Baru",
                description=f"**{self.manga.value}** - Chapter {self.chapter.value}",
                color=discord.Color.blue()
            )
            embed.add_field(name="Role", value=role, inline=True)
            embed.add_field(name="Rate", value=format_currency(final_rate), inline=True)
            
            if multiplier > 1.0:
                embed.add_field(name="Bonus", value="🌟 Popular Series (+30%)", inline=False)
            
            embed.set_footer(text=f"Assignment ID: {assignment_id}")
            
            # Update assignment with message_id
            message = await tasks_channel.send(
                content=f"{staff_role.mention if staff_role else '@Staff'} Tugas baru tersedia!",
                embed=embed,
                view=ClaimView(assignment_id)
            )
            
            # Update message_id in database
            db_conn = await db.get_db()
            try:
                await db_conn.execute(
                    "UPDATE assignments SET message_id = ? WHERE id = ?",
                    (message.id, assignment_id)
                )
                await db_conn.commit()
            finally:
                await db_conn.close()
        
        # Confirm to admin
        embed = discord.Embed(
            title="✅ Tugas Di-assign!",
            description=f"Berhasil assign tugas untuk **{self.manga.value}** chapter **{self.chapter.value}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Role", value=role, inline=True)
        embed.add_field(name="Rate", value=format_currency(final_rate), inline=True)
        embed.add_field(name="Assignment ID", value=str(assignment_id), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

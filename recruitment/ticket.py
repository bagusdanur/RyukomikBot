import discord
from discord.ext import commands
from config import REKRUT_CAT_ID, ROLE_STAFF_ID
from typing import Optional


class RecruitmentView(discord.ui.View):
    """View for recruitment ticket creation."""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📩 Buka Tiket Rekrutmen", style=discord.ButtonStyle.green, custom_id="rekrut_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Create a recruitment ticket channel."""
        guild = interaction.guild
        member = interaction.user
        
        # Check if user already has a ticket
        for channel in guild.text_channels:
            if member.name.lower() in channel.name.lower() and channel.category_id == REKRUT_CAT_ID:
                return await interaction.response.send_message(
                    f"❌ Kamu sudah memiliki tiket rekrutmen! {channel.mention}",
                    ephemeral=True
                )
        
        await interaction.response.defer(ephemeral=True)
        
        # Create ticket channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                attach_files=True,
                embed_links=True
            ),
        }
        
        # Add admin role permissions
        admin_role = guild.get_role(1524457168072343762)  # ROLE_ADMIN_ID
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True
            )
        
        # Add staff role permissions
        staff_role = guild.get_role(ROLE_STAFF_ID)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True
            )
        
        category = guild.get_channel(REKRUT_CAT_ID)
        channel_name = f"rekrutmen-{member.name}"
        
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Tiket rekrutmen untuk {member.display_name}"
        )
        
        # Welcome embed
        embed = discord.Embed(
            title="📩 Tiket Rekrutmen",
            description=f"Selamat datang {member.mention}!\n\n"
                       "Silakan jawab pertanyaan berikut untuk proses rekrutmen:",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="1. Nama Panggilan",
            value="Siapa nama panggilan kamu?",
            inline=False
        )
        
        embed.add_field(
            name="2. Role yang Dilamar",
            value="TL (Translator), PR (Proofreader), atau CL (Cleaner)?",
            inline=False
        )
        
        embed.add_field(
            name="3. Pengalaman",
            value="Ceritakan pengalaman kamu di scanlation (jika ada)",
            inline=False
        )
        
        embed.add_field(
            name="4. Portofolio",
            value="Jika ada, lampirkan hasil kerja sebelumnya",
            inline=False
        )
        
        embed.set_footer(text="Jawab pertanyaan di atas, admin akan segera merespon.")
        
        await ticket_channel.send(embed=embed)
        
        await interaction.followup.send(
            f"✅ Tiket rekrutmen berhasil dibuat! {ticket_channel.mention}",
            ephemeral=True
        )


class RecruitmentBot:
    """Recruitment system functionality."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    def setup(self):
        """Setup recruitment views and commands."""
        # Add persistent view
        self.bot.add_view(RecruitmentView())
        
        # Add commands
        @self.bot.command(name="rekrut")
        async def rekrut_command(ctx: commands.Context):
            """Send recruitment ticket embed."""
            if not ctx.author.guild_permissions.administrator:
                return await ctx.send("❌ Hanya admin yang bisa menggunakan command ini!")
            
            embed = discord.Embed(
                title="📩 Rekrutmen Ryukomik",
                description="Tertarik bergabung dengan Ryukomik?\n"
                           "Klik tombol di bawah untuk membuka tiket rekrutmen!",
                color=discord.Color.green()
            )
            embed.set_footer(text="Ryukomik Scanlation Group")
            
            await ctx.send(embed=embed, view=RecruitmentView())
            await ctx.message.delete()
        
        @self.bot.command(name="close")
        async def close_ticket(ctx: commands.Context):
            """Close a recruitment ticket."""
            if not ctx.channel.category_id or ctx.channel.category_id != REKRUT_CAT_ID:
                return await ctx.send("❌ Command ini hanya bisa digunakan di tiket rekrutmen!")
            
            if not ctx.author.guild_permissions.administrator:
                # Check if it's the ticket owner
                if ctx.author.name.lower() not in ctx.channel.name:
                    return await ctx.send("❌ Kamu tidak memiliki akses ke tiket ini!")
            
            embed = discord.Embed(
                title="🔒 Tiket Ditutup",
                description="Tiket ini akan ditutup dalam 5 detik...",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            
            import asyncio
            await asyncio.sleep(5)
            await ctx.channel.delete()


def setup_recruitment(bot: commands.Bot):
    """Setup recruitment system."""
    recruitment = RecruitmentBot(bot)
    recruitment.setup()
    return recruitment

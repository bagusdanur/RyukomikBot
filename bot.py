import discord
from discord.ext import commands
import asyncio
import os
from datetime import datetime

from config import TOKEN, GUILD_ID, STAFF_TASKS_CHANNEL_ID, ROLE_STAFF_ID, ROLE_ADMIN_ID
from database import setup_database
from panels.admin_panel import AdminPanelView
from panels.staff_panel import StaffPanelView
from panels.claim_view import ClaimView
from views.ticket_views import TicketSubmitView, TicketReviewView
from views.select_views import ReviewSelectView, SubmitSelectView, ConfirmPayView
from modals.assign_modal import AssignModal
from modals.submit_modal import SubmitModal
from modals.revisi_modal import RevisiModal
from modals.rekap_modal import RekapModal
from recruitment.ticket import setup_recruitment, RecruitmentView
from raw_downloader.asura import AsuraDownloader
from helpers.utils import is_admin, is_staff


# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True


class RyukomikBot(commands.Bot):
    """Main bot class for Ryukomik."""
    
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            application_id=None  # Will be set if needed
        )
        
        # Setup recruitment
        self.recruitment = setup_recruitment(self)
        
        # Raw downloader
        self.downloader = AsuraDownloader()
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        # Setup database
        await setup_database()
        
        # Add persistent views
        self.add_view(AdminPanelView())
        self.add_view(StaffPanelView())
        self.add_view(RecruitmentView())
        
        print("✅ Bot setup complete!")
    
    async def on_ready(self):
        """Called when the bot is ready."""
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")
        print(f"📡 Connected to {len(self.guilds)} guild(s)")
        
        # Sync slash commands
        try:
            synced = await self.tree.sync()
            print(f"✅ Synced {len(synced)} slash command(s)")
        except Exception as e:
            print(f"❌ Failed to sync commands: {e}")
        
        # Set activity
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Ryukomik Scanlation"
            )
        )


# Create bot instance
bot = RyukomikBot()


# ==================== SLASH COMMANDS ====================

@bot.tree.command(name="panels", description="Tampilkan panel admin/staff")
async def panels_command(interaction: discord.Interaction):
    """Show admin or staff panel."""
    if is_admin(interaction.user):
        embed = discord.Embed(
            title="🔧 Admin Panel",
            description="Panel untuk mengelola tugas dan pembayaran staff.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Fitur",
            value=(
                "📋 **Assign Tugas** - Assign tugas baru ke staff\n"
                "📝 **Review** - Review tugas yang di-submit\n"
                "📊 **Rekap** - Rekap pembayaran staff\n"
                "📈 **Stats** - Statistik keseluruhan"
            ),
            inline=False
        )
        await interaction.response.send_message(
            embed=embed,
            view=AdminPanelView(),
            ephemeral=True
        )
    elif is_staff(interaction.user):
        embed = discord.Embed(
            title="📋 Staff Panel",
            description="Panel untuk mengelola tugas dan penghasilan.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Fitur",
            value=(
                "📋 **Tugas Saya** - Lihat tugas yang sedang dikerjakan\n"
                "📤 **Submit Hasil** - Submit hasil kerja\n"
                "💰 **Penghasilan** - Lihat penghasilan"
            ),
            inline=False
        )
        await interaction.response.send_message(
            embed=embed,
            view=StaffPanelView(),
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "❌ Kamu tidak memiliki akses ke panel ini!",
            ephemeral=True
        )


@bot.tree.command(name="update-payrate", description="Update base rate untuk role tertentu")
async def update_payrate_command(
    interaction: discord.Interaction,
    role: str,
    new_rate: int
):
    """Update payrate for a role."""
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "❌ Hanya admin yang bisa mengubah payrate!",
            ephemeral=True
        )
    
    role = role.upper()
    if role not in ("TL", "PR", "CL"):
        return await interaction.response.send_message(
            "❌ Role harus TL, PR, atau CL!",
            ephemeral=True
        )
    
    if new_rate < 0 or new_rate > 50000:
        return await interaction.response.send_message(
            "❌ Rate harus antara 0 dan 50000!",
            ephemeral=True
        )
    
    # In a real implementation, this would update a config file or database
    # For now, we'll just acknowledge it
    embed = discord.Embed(
        title="✅ Payrate Diupdate",
        description=f"Base rate untuk **{role}** telah diupdate ke **Rp {new_rate:,}**",
        color=discord.Color.green()
    )
    embed.set_footer(text="Note: Update ini berlaku untuk tugas baru ke depannya.")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="search-manga", description="Cari manga dari Asura Scans")
async def search_manga_command(interaction: discord.Interaction, query: str):
    """Search for manga on Asura Scans."""
    await interaction.response.defer(ephemeral=True)
    
    results = await bot.downloader.search_manga(query)
    
    if not results:
        return await interaction.followup.send(
            f"🔍 Tidak ditemukan manga dengan query: **{query}**",
            ephemeral=True
        )
    
    embed = discord.Embed(
        title="🔍 Hasil Pencarian",
        description=f"Query: **{query}**",
        color=discord.Color.blue()
    )
    
    for i, manga in enumerate(results[:5], 1):
        embed.add_field(
            name=f"{i}. {manga.get('title', 'Unknown')}",
            value=(
                f"**ID:** {manga.get('id', 'N/A')}\n"
                f"**Status:** {manga.get('status', 'N/A')}\n"
                f"**Chapters:** {manga.get('chapter_count', 'N/A')}"
            ),
            inline=False
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="download-raw", description="Download chapter RAW dari Asura Scans")
async def download_raw_command(
    interaction: discord.Interaction,
    manga_id: str,
    chapter_id: str
):
    """Download a chapter from Asura Scans."""
    if not is_staff(interaction.user):
        return await interaction.response.send_message(
            "❌ Hanya staff yang bisa download RAW!",
            ephemeral=True
        )
    
    await interaction.response.defer(ephemeral=True)
    
    save_dir = os.path.join(os.path.dirname(__file__), "data", "raw")
    os.makedirs(save_dir, exist_ok=True)
    
    result = await bot.downloader.download_chapter(manga_id, chapter_id, save_dir)
    
    if result:
        embed = discord.Embed(
            title="✅ Download Berhasil",
            description=f"Chapter berhasil didownload!",
            color=discord.Color.green()
        )
        embed.add_field(name="Manga ID", value=manga_id, inline=True)
        embed.add_field(name="Chapter ID", value=chapter_id, inline=True)
        embed.add_field(name="Lokasi", value=f"`{result}`", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.followup.send(
            "❌ Gagal download chapter. Pastikan ID manga dan chapter benar!",
            ephemeral=True
        )


# ==================== MESSAGE COMMANDS ====================

@bot.command(name="panel")
async def panel_command(ctx: commands.Context):
    """Show panel via prefix command."""
    if is_admin(ctx.author):
        embed = discord.Embed(
            title="🔧 Admin Panel",
            description="Panel untuk mengelola tugas dan pembayaran staff.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, view=AdminPanelView())
    elif is_staff(ctx.author):
        embed = discord.Embed(
            title="📋 Staff Panel",
            description="Panel untuk mengelola tugas dan penghasilan.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed, view=StaffPanelView())
    else:
        await ctx.send("❌ Kamu tidak memiliki akses ke panel ini!")


@bot.command(name="help-ryukomik")
async def help_command(ctx: commands.Context):
    """Show help for Ryukomik bot."""
    embed = discord.Embed(
        title="📚 Ryukomik Bot - Help",
        description="Bot untuk mengelola tugas dan pembayaran staff Ryukomik.",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="📋 Slash Commands",
        value=(
            "`/panels` - Tampilkan panel admin/staff\n"
            "`/update-payrate` - Update base rate\n"
            "`/search-manga` - Cari manga\n"
            "`/download-raw` - Download chapter RAW"
        ),
        inline=False
    )
    
    embed.add_field(
        name="💬 Prefix Commands",
        value=(
            "`!panel` - Tampilkan panel\n"
            "`!rekrut` - Kirim embed rekrutmen (admin)\n"
            "`!close` - Tutup tiket rekrutmen\n"
            "`!help-ryukomik` - Tampilkan help ini"
        ),
        inline=False
    )
    
    embed.add_field(
        name="👥 Roles",
        value=(
            f"<@&{ROLE_ADMIN_ID}> - Admin (full access)\n"
            f"<@&{ROLE_STAFF_ID}> - Staff (submit & view tasks)"
        ),
        inline=False
    )
    
    await ctx.send(embed=embed)


# ==================== ERROR HANDLING ====================

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Handle command errors."""
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Kamu tidak memiliki izin untuk menggunakan command ini!")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argument tidak valid!")
    else:
        print(f"Error: {error}")
        await ctx.send("❌ Terjadi error saat menjalankan command!")


# ==================== RUN BOT ====================

if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_TOKEN tidak ditemukan di environment variables!")
        print("   Silakan buat file .env dan isi DISCORD_TOKEN")
        exit(1)
    
    bot.run(TOKEN)

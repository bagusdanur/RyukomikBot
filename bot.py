import discord
from discord.ext import commands
import asyncio
import os
from datetime import datetime

from config import TOKEN, GUILD_ID, STAFF_TASKS_CHANNEL_ID, ROLE_STAFF_ID, ROLE_ADMIN_ID
from database import get_assignments_by_status, setup_database
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
        open_assignments = await get_assignments_by_status("open")
        for assignment in open_assignments:
            if assignment.get("message_id"):
                self.add_view(ClaimView(assignment["id"]), message_id=assignment["message_id"])
        
        for status in ("claimed", "revision"):
            assignments = await get_assignments_by_status(status)
            for assignment in assignments:
                if assignment.get("ticket_channel_id"):
                    self.add_view(TicketSubmitView(assignment["id"]))
        
        submitted_assignments = await get_assignments_by_status("submitted")
        for assignment in submitted_assignments:
            if assignment.get("ticket_channel_id"):
                self.add_view(TicketReviewView(assignment["id"]))
        
        print("[OK] Bot setup complete!")
    
    async def on_ready(self):
        """Called when the bot is ready."""
        print(f"[OK] Logged in as {self.user} (ID: {self.user.id})")
        print(f"[INFO] Connected to {len(self.guilds)} guild(s)")
        
        # Sync slash commands
        try:
            synced = await self.tree.sync()
            print(f"[OK] Synced {len(synced)} slash command(s)")
        except Exception as e:
            print(f"[ERROR] Failed to sync commands: {e}")
        
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
async def panels_command(interaction: discord.Interaction, panel: str = "auto"):
    """Show admin or staff panel."""
    panel = panel.casefold()
    if panel not in ("auto", "admin", "staff"):
        return await interaction.response.send_message(
            "Panel harus `admin`, `staff`, atau kosong untuk auto.",
            ephemeral=False
        )

    if panel in ("auto", "admin") and is_admin(interaction.user):
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
            ephemeral=False
        )
    elif panel in ("auto", "staff") and is_staff(interaction.user):
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
            ephemeral=False
        )
    else:
        await interaction.response.send_message(
            "❌ Kamu tidak memiliki akses ke panel ini!",
            ephemeral=False
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
            ephemeral=False
        )
    
    role = role.upper()
    if role not in ("TL", "TS", "TL+TS"):
        return await interaction.response.send_message(
            "Role harus TL, TS, atau TL+TS!",
            ephemeral=False
        )
    
    if new_rate < 0 or new_rate > 50000:
        return await interaction.response.send_message(
            "❌ Rate harus antara 0 dan 50000!",
            ephemeral=False
        )
    
    # In a real implementation, this would update a config file or database
    # For now, we'll just acknowledge it
    embed = discord.Embed(
        title="✅ Payrate Diupdate",
        description=f"Base rate untuk **{role}** telah diupdate ke **Rp {new_rate:,}**",
        color=discord.Color.green()
    )
    embed.set_footer(text="Note: Update ini berlaku untuk tugas baru ke depannya.")
    
    await interaction.response.send_message(embed=embed, ephemeral=False)


@bot.tree.command(name="search-manga", description="Cari manga dari Asura Scans")
async def search_manga_command(interaction: discord.Interaction, query: str):
    """Search for manga on Asura Scans."""
    await interaction.response.defer(ephemeral=False)
    
    results = await bot.downloader.search_manga(query)
    
    if not results:
        return await interaction.followup.send(
            f"🔍 Tidak ditemukan manga dengan query: **{query}**",
            ephemeral=False
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
    
    await interaction.followup.send(embed=embed, ephemeral=False)


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
            ephemeral=False
        )


@bot.tree.command(name="raw-search", description="Cari komik RAW dari Asura Scans")
async def raw_search_command(interaction: discord.Interaction, query: str):
    """PRD-compatible raw search command."""
    await search_manga_command(interaction, query)


@bot.tree.command(name="raw-chapters", description="Lihat daftar chapter RAW")
async def raw_chapters_command(interaction: discord.Interaction, manga_id: str):
    """List chapters for a manga."""
    await interaction.response.defer(ephemeral=False)
    chapters = await bot.downloader.get_chapter_list(manga_id)
    if not chapters:
        return await interaction.followup.send(
            f"Tidak ada chapter untuk manga ID **{manga_id}**.",
            ephemeral=False,
        )

    embed = discord.Embed(
        title="Daftar Chapter RAW",
        description=f"Manga ID: **{manga_id}**",
        color=discord.Color.blue(),
    )
    for chapter in chapters[:20]:
        chapter_id = chapter.get("id", chapter.get("chapter_id", "N/A"))
        title = chapter.get("title", chapter.get("name", f"Chapter {chapter_id}"))
        embed.add_field(name=str(title), value=f"ID: `{chapter_id}`", inline=False)
    if len(chapters) > 20:
        embed.set_footer(text=f"Menampilkan 20 dari {len(chapters)} chapter.")
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="raw-download", description="Download chapter RAW dari Asura Scans")
async def raw_download_command(
    interaction: discord.Interaction,
    manga_id: str,
    chapter_id: str
):
    """PRD-compatible raw download command."""
    await download_raw_command(interaction, manga_id, chapter_id)


@bot.tree.command(name="raw-download-batch", description="Batch download chapter RAW")
async def raw_download_batch_command(
    interaction: discord.Interaction,
    manga_id: str,
    chapter_ids: str
):
    """Download multiple chapters. chapter_ids is comma-separated."""
    if not is_staff(interaction.user):
        return await interaction.response.send_message(
            "Hanya staff yang bisa download RAW!",
            ephemeral=False,
        )

    await interaction.response.defer(ephemeral=False)
    save_dir = os.path.join(os.path.dirname(__file__), "data", "raw")
    os.makedirs(save_dir, exist_ok=True)

    ids = [chapter_id.strip() for chapter_id in chapter_ids.split(",") if chapter_id.strip()]
    if not ids:
        return await interaction.followup.send("Isi minimal satu chapter ID.", ephemeral=False)

    results = []
    for chapter_id in ids[:10]:
        result = await bot.downloader.download_chapter(manga_id, chapter_id, save_dir)
        results.append((chapter_id, result))

    embed = discord.Embed(
        title="Batch Download RAW",
        description=f"Manga ID: **{manga_id}**",
        color=discord.Color.green(),
    )
    for chapter_id, result in results:
        status = f"OK: `{result}`" if result else "Gagal"
        embed.add_field(name=f"Chapter {chapter_id}", value=status, inline=False)
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="raw-update", description="Cek update RAW terbaru")
async def raw_update_command(interaction: discord.Interaction, query: str = ""):
    """Best-effort latest raw update command using the configured Asura API."""
    await interaction.response.defer(ephemeral=False)
    results = await bot.downloader.search_manga(query or "latest")
    if not results:
        return await interaction.followup.send(
            "Belum bisa mengambil update RAW terbaru dari API.",
            ephemeral=False,
        )

    embed = discord.Embed(title="Update RAW Terbaru", color=discord.Color.blue())
    for manga in results[:10]:
        embed.add_field(
            name=manga.get("title", "Unknown"),
            value=(
                f"ID: `{manga.get('id', 'N/A')}`\n"
                f"Status: {manga.get('status', 'N/A')}\n"
                f"Chapters: {manga.get('chapter_count', 'N/A')}"
            ),
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=False)
    
    await interaction.response.defer(ephemeral=False)
    
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
        
        await interaction.followup.send(embed=embed, ephemeral=False)
    else:
        await interaction.followup.send(
            "❌ Gagal download chapter. Pastikan ID manga dan chapter benar!",
            ephemeral=False
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
            "`/raw-update` - Cek update RAW terbaru\n"
            "`/raw-search` - Cari manga\n"
            "`/raw-chapters` - Lihat chapter\n"
            "`/raw-download` - Download chapter RAW\n"
            "`/raw-download-batch` - Batch download RAW"
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


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Handle slash command errors."""
    print(f"Slash command error: {error}")
    message = "Terjadi error saat menjalankan slash command!"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=False)
    else:
        await interaction.response.send_message(message, ephemeral=False)


# ==================== RUN BOT ====================

if __name__ == "__main__":
    if not TOKEN:
        print("[ERROR] DISCORD_TOKEN tidak ditemukan di environment variables!")
        print("   Silakan buat file .env dan isi DISCORD_TOKEN")
        exit(1)
    
    bot.run(TOKEN)

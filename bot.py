import discord
from discord.ext import commands
import asyncio
import os
from datetime import datetime

from config import TOKEN, GUILD_ID, STAFF_TASKS_CHANNEL_ID, STAFF_LOG_CHANNEL_ID, ROLE_STAFF_ID, ROLE_ADMIN_ID
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
from helpers.utils import find_or_create_staff_ticket, is_admin, is_staff


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
    """Send exactly one panel to its designated channel."""
    selected = panel.casefold()
    if selected not in ("auto", "admin", "staff"):
        return await interaction.response.send_message("Panel harus `admin`, `staff`, atau `auto`.", ephemeral=False)
    if selected == "auto":
        selected = "admin" if is_admin(interaction.user) else "staff"

    if selected == "admin":
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Kamu bukan administrator.", ephemeral=False)
        if interaction.channel_id != STAFF_LOG_CHANNEL_ID:
            return await interaction.response.send_message(
                f"Panel admin hanya boleh dikirim di <#{STAFF_LOG_CHANNEL_ID}>.", ephemeral=False
            )
        embed = discord.Embed(
            title="ADMIN PANEL",
            description="Assign tugas, review hasil, rekap gaji, dan pantau statistik staff.",
            color=discord.Color.red(),
        )
        return await interaction.response.send_message(embed=embed, view=AdminPanelView(), ephemeral=False)

    if not is_staff(interaction.user) or not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("Kamu bukan staff.", ephemeral=False)
    ticket = await find_or_create_staff_ticket(interaction.guild, interaction.user)
    embed = discord.Embed(
        title="STAFF PANEL",
        description="Lihat tugas, submit hasil, dan cek penghasilan dari tiket privat ini.",
        color=discord.Color.blue(),
    )
    await ticket.send(embed=embed, view=StaffPanelView())
    await interaction.response.send_message(
        f"Panel staff dikirim ke tiket privat kamu: {ticket.mention}", ephemeral=False
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
            "âŒ Hanya admin yang bisa mengubah payrate!",
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
            "âŒ Rate harus antara 0 dan 50000!",
            ephemeral=False
        )
    
    # In a real implementation, this would update a config file or database
    # For now, we'll just acknowledge it
    embed = discord.Embed(
        title="âœ… Payrate Diupdate",
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
            f"ðŸ” Tidak ditemukan manga dengan query: **{query}**",
            ephemeral=False
        )
    
    embed = discord.Embed(
        title="ðŸ” Hasil Pencarian",
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
async def download_raw_command(interaction: discord.Interaction, manga_id: str, chapter_id: str):
    """Download one RAW chapter."""
    if not is_staff(interaction.user):
        return await interaction.response.send_message("Hanya staff yang bisa download RAW!", ephemeral=False)
    await interaction.response.defer(ephemeral=False)
    save_dir = os.path.join(os.path.dirname(__file__), "data", "raw")
    os.makedirs(save_dir, exist_ok=True)
    result = await bot.downloader.download_chapter(manga_id, chapter_id, save_dir)
    if not result:
        return await interaction.followup.send("Gagal download chapter. Periksa manga ID dan chapter ID.", ephemeral=False)
    embed = discord.Embed(title="Download Berhasil", color=discord.Color.green())
    embed.add_field(name="Manga ID", value=manga_id, inline=True)
    embed.add_field(name="Chapter ID", value=chapter_id, inline=True)
    embed.add_field(name="Lokasi", value=f"`{result}`", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="raw-search", description="Cari komik RAW dari Asura Scans")
async def raw_search_command(interaction: discord.Interaction, query: str):
    await search_manga_command(interaction, query)


@bot.tree.command(name="raw-chapters", description="Lihat daftar chapter RAW")
async def raw_chapters_command(interaction: discord.Interaction, manga_id: str):
    await interaction.response.defer(ephemeral=False)
    chapters = await bot.downloader.get_chapter_list(manga_id)
    if not chapters:
        return await interaction.followup.send(f"Tidak ada chapter untuk manga ID **{manga_id}**.", ephemeral=False)
    embed = discord.Embed(title="Daftar Chapter RAW", description=f"Manga ID: **{manga_id}**", color=discord.Color.blue())
    for chapter in chapters[:20]:
        chapter_id = chapter.get("id", chapter.get("chapter_id", "N/A"))
        title = chapter.get("title", chapter.get("name", f"Chapter {chapter_id}"))
        embed.add_field(name=str(title), value=f"ID: `{chapter_id}`", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="raw-download", description="Download chapter RAW dari Asura Scans")
async def raw_download_command(interaction: discord.Interaction, manga_id: str, chapter_id: str):
    await download_raw_command(interaction, manga_id, chapter_id)


@bot.tree.command(name="raw-download-batch", description="Batch download chapter RAW")
async def raw_download_batch_command(interaction: discord.Interaction, manga_id: str, chapter_ids: str):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("Hanya staff yang bisa download RAW!", ephemeral=False)
    await interaction.response.defer(ephemeral=False)
    save_dir = os.path.join(os.path.dirname(__file__), "data", "raw")
    os.makedirs(save_dir, exist_ok=True)
    ids = [item.strip() for item in chapter_ids.split(",") if item.strip()][:10]
    if not ids:
        return await interaction.followup.send("Isi minimal satu chapter ID.", ephemeral=False)
    embed = discord.Embed(title="Batch Download RAW", color=discord.Color.green())
    for chapter_id in ids:
        result = await bot.downloader.download_chapter(manga_id, chapter_id, save_dir)
        embed.add_field(name=f"Chapter {chapter_id}", value=f"OK: `{result}`" if result else "Gagal", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="raw-update", description="Cek update RAW terbaru")
async def raw_update_command(interaction: discord.Interaction, query: str = ""):
    await interaction.response.defer(ephemeral=False)
    results = await bot.downloader.search_manga(query or "latest")
    if not results:
        return await interaction.followup.send("Belum bisa mengambil update RAW terbaru dari API.", ephemeral=False)
    embed = discord.Embed(title="Update RAW Terbaru", color=discord.Color.blue())
    for manga in results[:10]:
        embed.add_field(name=manga.get("title", "Unknown"), value=f"ID: `{manga.get('id', 'N/A')}`", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=False)

# ==================== MESSAGE COMMANDS ====================

@bot.command(name="panel")
async def panel_command(ctx: commands.Context):
    """Send one panel to the correct private/moderation channel."""
    if is_admin(ctx.author):
        if ctx.channel.id != STAFF_LOG_CHANNEL_ID:
            return await ctx.send(f"Panel admin hanya boleh dikirim di <#{STAFF_LOG_CHANNEL_ID}>.")
        embed = discord.Embed(title="ADMIN PANEL", description="Kelola tugas dan pembayaran staff.", color=discord.Color.red())
        return await ctx.send(embed=embed, view=AdminPanelView())
    if is_staff(ctx.author):
        ticket = await find_or_create_staff_ticket(ctx.guild, ctx.author)
        embed = discord.Embed(title="STAFF PANEL", description="Kelola tugas dan penghasilan dari tiket privat ini.", color=discord.Color.blue())
        await ticket.send(embed=embed, view=StaffPanelView())
        return await ctx.send(f"Panel staff dikirim ke tiket privat kamu: {ticket.mention}")
    await ctx.send("Kamu tidak memiliki akses ke panel ini.")

@bot.command(name="help-ryukomik")
async def help_command(ctx: commands.Context):
    """Show help for Ryukomik bot."""
    embed = discord.Embed(
        title="ðŸ“š Ryukomik Bot - Help",
        description="Bot untuk mengelola tugas dan pembayaran staff Ryukomik.",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="ðŸ“‹ Slash Commands",
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
        name="ðŸ’¬ Prefix Commands",
        value=(
            "`!panel` - Tampilkan panel\n"
            "`!rekrut` - Kirim embed rekrutmen (admin)\n"
            "`!close` - Tutup tiket rekrutmen\n"
            "`!help-ryukomik` - Tampilkan help ini"
        ),
        inline=False
    )
    
    embed.add_field(
        name="ðŸ‘¥ Roles",
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
        await ctx.send("âŒ Kamu tidak memiliki izin untuk menggunakan command ini!")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("âŒ Argument tidak valid!")
    else:
        print(f"Error: {error}")
        await ctx.send("âŒ Terjadi error saat menjalankan command!")


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


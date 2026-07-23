import discord
from discord.ext import commands, tasks
import asyncio
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Literal

from config import TOKEN, GUILD_ID, STAFF_TASKS_CHANNEL_ID, STAFF_LOG_CHANNEL_ID, ROLE_STAFF_ID, ROLE_ADMIN_ID
from database import get_assignments_by_status, setup_database
from panels.admin_panel import AdminPanelView, upsert_admin_panel
from panels.staff_panel import StaffPanelView, upsert_staff_panel
from panels.claim_view import ClaimView
from views.ticket_views import (
    ApproveDynamicItem, LegacyTaskView, ReviseDynamicItem, SubmitDynamicItem,
)
from views.select_views import ReviewSelectView, SubmitSelectView, ConfirmPayView
from views.raw_views import RawSearchView, create_filebin_download
from modals.assign_modal import AssignModal
from modals.revisi_modal import RevisiModal
from modals.rekap_modal import RekapModal
from recruitment.ticket import setup_recruitment, RecruitmentView
from raw_downloader import get_downloader
from helpers.utils import ROLE_PAYRATES, find_or_create_staff_ticket, is_admin, is_staff
from helpers.panel_content import build_admin_panel_embed, build_guide_embed, build_staff_panel_embed
import payment_service as payments
from views.payment_views import (
    ConfirmPayPayoutDynamic, IncomeMenuView, PayPayoutDynamic, PayoutAdminView, RejectPayoutDynamic,
    RetryInvoiceDynamic,
)
import database as db


# Discord gateway intents required by prefix commands, role checks, and tickets.
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
        
        self.commands_synced = False
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        # Setup database
        await setup_database()
        await payments.setup_payment_tables()
        
        # Add persistent views
        self.recruitment.register_persistent_views()
        self.add_view(AdminPanelView())
        self.add_view(StaffPanelView())
        self.add_view(IncomeMenuView())
        self.add_view(LegacyTaskView())
        self.add_dynamic_items(SubmitDynamicItem, ApproveDynamicItem, ReviseDynamicItem)
        self.add_dynamic_items(
            PayPayoutDynamic, ConfirmPayPayoutDynamic,
            RejectPayoutDynamic, RetryInvoiceDynamic,
        )
        open_assignments = await get_assignments_by_status("open")
        for assignment in open_assignments:
            if assignment.get("message_id"):
                self.add_view(ClaimView(assignment["id"]), message_id=assignment["message_id"])
        
        if not scheduled_payout_loop.is_running():
            scheduled_payout_loop.start()
        if not workflow_reminder_loop.is_running():
            workflow_reminder_loop.start()
        print("[OK] Bot setup complete!")
    
    async def on_ready(self):
        """Called when the bot is ready."""
        print(f"[OK] Logged in as {self.user} (ID: {self.user.id})")
        print(f"[INFO] Connected to {len(self.guilds)} guild(s)")
        
        # Remove stale guild-scoped commands first. Having the same command both
        # globally and per-guild makes Discord display duplicate entries.
        try:
            if not self.commands_synced:
                guild_scope = discord.Object(id=GUILD_ID)
                self.tree.clear_commands(guild=guild_scope)
                await self.tree.sync(guild=guild_scope)
                synced = await self.tree.sync()
                self.commands_synced = True
                print(f"[OK] Cleared stale guild commands for {GUILD_ID}")
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


@tasks.loop(hours=1)
async def scheduled_payout_loop():
    """Create idempotent 4/19 payout batches and notify private/admin channels."""
    created = await payments.create_due_scheduled_payouts()
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    admin_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
    for item in created:
        staff_id = int(item.get("staff_id") or 0)
        if item.get("missing_method"):
            from helpers.utils import find_ticket
            ticket = await find_ticket(guild, staff_id)
            if ticket:
                member = guild.get_member(staff_id)
                await ticket.send(
                    content=member.mention if member else None,
                    embed=discord.Embed(
                        title="Lengkapi Metode Pembayaran",
                        description=f"Siklus gaji **{item['cycle_key']}** belum dapat dibuat karena tujuan transfer belum tersedia.",
                        color=discord.Color.orange(),
                    ),
                )
        detail = await payments.payout_detail(item["id"])
        if admin_channel and detail:
            member = guild.get_member(int(detail["staff_id"]))
            embed = discord.Embed(
                title=f"Gajian Terjadwal #{detail['id']}",
                description=f"Siklus **{detail['cycle_key']}** untuk {member.mention if member else detail['staff_id']}.",
                color=discord.Color.gold(),
            )
            embed.add_field(name="Total", value=f"Rp {detail['total_amount']:,.0f}".replace(",", "."), inline=True)
            embed.add_field(name="Chapter", value=str(detail["chapter_count"]), inline=True)
            if detail["status"] == "awaiting_method":
                embed.add_field(name="Status", value="Menunggu metode pembayaran staff", inline=False)
            await admin_channel.send(embed=embed, view=PayoutAdminView(detail["id"], detail["status"]))


@scheduled_payout_loop.before_loop
async def before_scheduled_payout_loop():
    await bot.wait_until_ready()


@tasks.loop(hours=1)
async def workflow_reminder_loop():
    """Send each actionable reminder once, even after process restarts."""
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    admin_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
    from helpers.utils import find_ticket
    for item in await db.get_reminder_candidates():
        assignment_id = int(item["id"])
        if item["status"] == "submitted":
            key = f"review-24h:{assignment_id}:{item.get('submitted_at')}"
            if admin_channel and await db.claim_reminder(key, assignment_id, "admin"):
                await admin_channel.send(embed=discord.Embed(
                    title="⏳ Hasil Belum Direview",
                    description=(
                        f"Tugas **#{assignment_id} — {item['manga']} Ch. {item['chapter']}** "
                        "sudah menunggu review lebih dari 24 jam."
                    ),
                    color=discord.Color.orange(),
                ))
            continue
        deadline = str(item.get("deadline_at") or "")[:10]
        today = datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()
        overdue = bool(deadline and deadline < today)
        key = f"{'overdue' if overdue else 'deadline-h1'}:{assignment_id}:{deadline}"
        if not await db.claim_reminder(key, assignment_id, "staff"):
            continue
        ticket = await find_ticket(guild, int(item.get("staff_id") or 0))
        if ticket:
            member = guild.get_member(int(item["staff_id"]))
            await ticket.send(
                content=member.mention if member else None,
                embed=discord.Embed(
                    title="⚠️ Tugas Melewati Deadline" if overdue else "⏰ Deadline Besok",
                    description=(
                        f"**#{assignment_id} — {item['manga']} Ch. {item['chapter']}**\n"
                        f"Deadline: **{deadline}**. "
                        + ("Gunakan **Bantuan Tugas** jika ada kendala." if overdue else "Pastikan hasil segera diselesaikan.")
                    ),
                    color=discord.Color.red() if overdue else discord.Color.gold(),
                ),
            )


@workflow_reminder_loop.before_loop
async def before_workflow_reminder_loop():
    await bot.wait_until_ready()


# ==================== SLASH COMMANDS ====================

@bot.tree.command(name="panels", description="Tampilkan panel admin/staff")
@discord.app_commands.describe(
    panel="Pilih admin atau staff",
    staff="Staff tujuan saat administrator membuat Staff Panel",
)
async def panels_command(
    interaction: discord.Interaction,
    panel: Literal["auto", "admin", "staff"] = "auto",
    staff: discord.Member = None,
):
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
        await interaction.response.defer(ephemeral=False)
        _, created = await upsert_admin_panel(interaction.channel)
        return await interaction.followup.send(
            f"Admin Panel berhasil {'dibuat' if created else 'diperbarui'} di channel ini."
        )

    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("Command ini hanya tersedia di server.", ephemeral=False)

    actor_is_admin = is_admin(interaction.user)
    if actor_is_admin:
        target = staff
        if target is None:
            return await interaction.response.send_message(
                "Pilih staff tujuan pada parameter `staff`, contoh: `/panels staff staff:@nama`.",
                ephemeral=False,
            )
    else:
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Kamu bukan staff.", ephemeral=False)
        if staff and staff.id != interaction.user.id:
            return await interaction.response.send_message(
                "Staff hanya dapat membuat panel untuk dirinya sendiri.", ephemeral=False
            )
        target = interaction.user

    if not is_staff(target):
        return await interaction.response.send_message(
            "Member tujuan belum memiliki role Staff.", ephemeral=False
        )
    ticket = await find_or_create_staff_ticket(interaction.guild, target)
    _, created = await upsert_staff_panel(ticket, target)
    await interaction.response.send_message(
        f"Staff Panel untuk {target.mention} berhasil {'dibuat' if created else 'diperbarui'} di {ticket.mention}.", ephemeral=False
    )


@bot.tree.command(name="panduan", description="Tampilkan panduan kerja sesuai role pengguna")
async def guide_command(interaction: discord.Interaction):
    audience = "admin" if is_admin(interaction.user) else "staff" if is_staff(interaction.user) else "all"
    await interaction.response.send_message(embed=build_guide_embed(audience), ephemeral=False)


@bot.tree.command(name="menu", description="Pindahkan panel kerja ke pesan paling baru")
async def menu_command(interaction: discord.Interaction):
    """Move the user's canonical panel to the bottom without leaving duplicates."""
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("Command ini hanya dapat digunakan di channel server.", ephemeral=False)

    if is_admin(interaction.user) and interaction.channel_id == STAFF_LOG_CHANNEL_ID:
        old_panel, _ = await upsert_admin_panel(interaction.channel)
        try:
            await old_panel.delete()
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.response.send_message(
                "Panel tidak dapat dipindahkan. Pastikan bot memiliki izin **Manage Messages**; panel lama tetap tersedia melalui pesan pin.",
                ephemeral=False,
            )
        await interaction.response.send_message("Panel administrator dipindahkan ke bawah.", ephemeral=False)
        await upsert_admin_panel(interaction.channel)
        return

    if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
        return await interaction.response.send_message("Command ini hanya untuk staff atau administrator.", ephemeral=False)

    ticket = await find_or_create_staff_ticket(interaction.guild, interaction.user)
    if interaction.channel_id != ticket.id:
        return await interaction.response.send_message(
            f"Gunakan `/menu` di tiket staff milikmu: {ticket.mention}", ephemeral=False
        )

    old_panel, _ = await upsert_staff_panel(ticket, interaction.user)
    try:
        await old_panel.delete()
    except (discord.Forbidden, discord.HTTPException):
        return await interaction.response.send_message(
            "Panel tidak dapat dipindahkan. Pastikan bot memiliki izin **Manage Messages**; panel lama tetap tersedia melalui pesan pin.",
            ephemeral=False,
        )
    await interaction.response.send_message("Panel kerjamu dipindahkan ke bawah.", ephemeral=False)
    await upsert_staff_panel(ticket, interaction.user)

@bot.tree.command(name="update-payrate", description="Ubah base rate untuk tugas baru")
@discord.app_commands.describe(role="Role TL, TS, atau TL+TS", new_rate="Base rate baru dalam Rupiah")
async def update_payrate_command(
    interaction: discord.Interaction,
    role: Literal["TL", "TS", "TL+TS"],
    new_rate: int,
):
    """Persist the base payrate used by future assignments."""
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Hanya administrator yang dapat mengubah payrate.", ephemeral=False
        )

    normalized_role = role.strip().upper().replace(" ", "")
    if normalized_role not in ("TL", "TS", "TL+TS"):
        return await interaction.response.send_message(
            "Role harus TL, TS, atau TL+TS.", ephemeral=False
        )
    maximum_rate = ROLE_PAYRATES[normalized_role]["max"]
    if new_rate < 0 or new_rate > maximum_rate:
        return await interaction.response.send_message(
            f"Base rate {normalized_role} harus antara Rp 0 dan Rp {maximum_rate:,.0f}.".replace(",", "."),
            ephemeral=False,
        )

    await db.set_role_payrate(normalized_role, new_rate)
    embed = discord.Embed(
        title="Payrate Berhasil Diperbarui",
        description=(
            f"Base rate **{normalized_role}** sekarang **Rp {new_rate:,.0f}**. "
            "Nilai ini berlaku untuk tugas baru yang tidak memakai Rate Override."
        ).replace(",", "."),
        color=discord.Color.green(),
    )
    embed.set_footer(text="Tugas lama dan manual override tidak berubah.")
    await interaction.response.send_message(embed=embed, ephemeral=False)

async def search_manga_command(interaction: discord.Interaction, query: str, source: str = "asura"):
    """Search for manga on Asura Scans or Doujiva."""
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Pencarian RAW bebas hanya untuk administrator. Staff gunakan **Download RAW** pada Staff Panel agar chapter sesuai tugas.",
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=False)
    downloader = get_downloader(source)
    results = await downloader.search_manga(query)
    
    if not results:
        return await interaction.followup.send(
            f"ðŸ” Tidak ditemukan manga di **{source.title()}** dengan query: **{query}**",
            ephemeral=False
        )
    
    embed = discord.Embed(
        title=f"ðŸ” Hasil Pencarian ({source.title()})",
        description=f"Query: **{query}**",
        color=discord.Color.blue()
    )
    
    for i, manga in enumerate(results[:5], 1):
        embed.add_field(
            name=f"{i}. {manga.get('title', 'Unknown')}",
            value=(
                f"**ID:** `{manga.get('id', 'N/A')}`\n"
                f"**Status:** {manga.get('status', 'N/A')}\n"
                f"**Chapters:** {manga.get('chapter_count', 'N/A')}"
            ),
            inline=False
        )
    
    await interaction.followup.send(embed=embed, view=RawSearchView(source, results), ephemeral=False)


async def download_raw_command(interaction: discord.Interaction, manga_id: str, chapter_id: str, source: str = "asura"):
    """Download one RAW chapter."""
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Download RAW bebas hanya untuk administrator. Staff gunakan **Download RAW** pada Staff Panel.",
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=False)
    filebin_url, completed = await create_filebin_download(source, manga_id, [chapter_id])
    if not filebin_url:
        return await interaction.followup.send(f"Gagal download atau upload ke Filebin dari **{source.title()}**. Coba lagi nanti.", ephemeral=False)
    embed = discord.Embed(title=f"RAW Siap Diunduh ({source.title()})", color=discord.Color.green())
    embed.add_field(name="Manga ID", value=manga_id, inline=True)
    embed.add_field(name="Chapter", value=", ".join(completed), inline=True)
    embed.add_field(name="Link Download", value=f"[Buka Filebin]({filebin_url})", inline=False)
    embed.set_footer(text="File lokal VPS sudah dihapus setelah upload.")
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="raw-search", description="Cari komik RAW dari Asura Scans atau Doujiva")
@discord.app_commands.describe(query="Judul atau kata kunci komik", source="Sumber RAW (asura atau doujiva)")
async def raw_search_command(interaction: discord.Interaction, query: str, source: Literal["asura", "doujiva"] = "asura"):
    await search_manga_command(interaction, query, source)


@bot.tree.command(name="status-bot", description="Cek kesehatan database, Discord, dan API RAW")
async def status_bot_command(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        return await interaction.response.send_message("Hanya administrator yang dapat melihat status sistem.")
    await interaction.response.defer()

    async def check_db():
        started = time.perf_counter()
        connection = await db.get_db()
        try:
            await (await connection.execute("SELECT 1")).fetchone()
            return True, round((time.perf_counter() - started) * 1000)
        finally:
            await connection.close()

    async def check_raw(source):
        started = time.perf_counter()
        try:
            result = await get_downloader(source).search_manga("solo")
            return bool(result), round((time.perf_counter() - started) * 1000)
        except Exception:
            return False, round((time.perf_counter() - started) * 1000)

    database_status, asura_status, doujiva_status = await asyncio.gather(check_db(), check_raw("asura"), check_raw("doujiva"))
    embed = discord.Embed(title="Status Ryukomik Bot", description="Pemeriksaan langsung komponen utama.", color=discord.Color.green() if all(x[0] for x in (database_status, asura_status, doujiva_status)) else discord.Color.orange())
    embed.add_field(name="Discord Gateway", value=f"Online • {round(bot.latency * 1000)} ms", inline=False)
    for name, result in (("Database", database_status), ("Asura API", asura_status), ("Doujiva API", doujiva_status)):
        embed.add_field(name=name, value=f"{'Sehat' if result[0] else 'Bermasalah'} • {result[1]} ms")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="raw-chapters", description="Lihat daftar chapter RAW")
@discord.app_commands.describe(manga_id="Slug komik, contoh: lets-do-it-after-work", source="Sumber RAW (asura atau doujiva)")
async def raw_chapters_command(interaction: discord.Interaction, manga_id: str, source: Literal["asura", "doujiva"] = "asura"):
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Daftar chapter bebas hanya untuk administrator. Staff gunakan **Download RAW** pada Staff Panel.",
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=False)
    downloader = get_downloader(source)
    chapters = await downloader.get_chapter_list(manga_id)
    if not chapters:
        return await interaction.followup.send(f"Tidak ada chapter untuk manga ID **{manga_id}** di **{source.title()}**.", ephemeral=False)
    embed = discord.Embed(title=f"Daftar Chapter RAW ({source.title()})", description=f"Manga ID: **{manga_id}**", color=discord.Color.blue())
    for chapter in chapters[:20]:
        chapter_id = chapter.get("id", chapter.get("chapter_id", "N/A"))
        title = chapter.get("title", chapter.get("name", f"Chapter {chapter_id}"))
        embed.add_field(name=str(title), value=f"ID: `{chapter_id}`", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="raw-download", description="Download chapter RAW dari Asura Scans atau Doujiva")
@discord.app_commands.describe(manga_id="Slug komik, contoh: lets-do-it-after-work", chapter_id="Nomor/slug chapter, contoh: 1", source="Sumber RAW")
async def raw_download_command(interaction: discord.Interaction, manga_id: str, chapter_id: str, source: Literal["asura", "doujiva"] = "asura"):
    await download_raw_command(interaction, manga_id, chapter_id, source)


@bot.tree.command(name="raw-download-batch", description="Batch download chapter RAW")
@discord.app_commands.describe(manga_id="Slug komik, contoh: lets-do-it-after-work", chapter_ids="Chapter dipisah koma, contoh: 1,2,3", source="Sumber RAW")
async def raw_download_batch_command(interaction: discord.Interaction, manga_id: str, chapter_ids: str, source: Literal["asura", "doujiva"] = "asura"):
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Batch RAW bebas hanya untuk administrator. Staff gunakan **Download RAW** pada Staff Panel.",
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=False)
    ids = [item.strip() for item in chapter_ids.split(",") if item.strip()][:10]
    if not ids:
        return await interaction.followup.send("Isi minimal satu chapter ID.", ephemeral=False)
    filebin_url, completed = await create_filebin_download(source, manga_id, ids)
    if not filebin_url:
        return await interaction.followup.send("Download atau upload Filebin gagal. Coba kembali nanti.")
    embed = discord.Embed(title=f"Batch RAW Siap Diunduh ({source.title()})", color=discord.Color.green())
    embed.add_field(name="Chapter Berhasil", value=", ".join(completed), inline=False)
    failed = [chapter for chapter in ids if chapter not in completed]
    if failed:
        embed.add_field(name="Chapter Gagal", value=", ".join(failed), inline=False)
    embed.add_field(name="Link Download", value=f"[Buka Filebin]({filebin_url})", inline=False)
    embed.set_footer(text="File lokal VPS sudah dihapus setelah upload.")
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="raw-update", description="Cek update RAW terbaru")
@discord.app_commands.describe(query="Kata kunci komik (opsional)", source="Sumber RAW (asura atau doujiva)")
async def raw_update_command(interaction: discord.Interaction, query: str = "", source: Literal["asura", "doujiva"] = "asura"):
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Update RAW bebas hanya untuk administrator. Staff gunakan **Download RAW** pada Staff Panel.",
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=False)
    downloader = get_downloader(source)
    results = await downloader.search_manga(query or "latest")
    if not results:
        return await interaction.followup.send(f"Belum bisa mengambil update RAW terbaru dari API {source.title()}.", ephemeral=False)
    embed = discord.Embed(title=f"Update RAW Terbaru ({source.title()})", color=discord.Color.blue())
    for manga in results[:10]:
        embed.add_field(name=manga.get("title", "Unknown"), value=f"ID: `{manga.get('id', 'N/A')}`", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=False)

# ==================== MESSAGE COMMANDS ====================

@bot.command(name="panel")
async def panel_command(ctx: commands.Context, panel: str = "auto", staff: discord.Member = None):
    """Send one panel to the correct private/moderation channel."""
    selected = panel.casefold()
    if selected == "auto":
        selected = "admin" if is_admin(ctx.author) else "staff"
    if selected == "admin" and is_admin(ctx.author):
        if ctx.channel.id != STAFF_LOG_CHANNEL_ID:
            return await ctx.send(f"Panel admin hanya boleh dikirim di <#{STAFF_LOG_CHANNEL_ID}>.")
        _, created = await upsert_admin_panel(ctx.channel)
        return await ctx.send(f"Admin Panel {'dibuat' if created else 'diperbarui'} di channel ini.")
    if selected == "staff":
        if is_admin(ctx.author):
            target = staff
            if target is None:
                return await ctx.send("Gunakan `!panel staff @nama` untuk memilih staff tujuan.")
        elif is_staff(ctx.author):
            target = ctx.author
        else:
            return await ctx.send("Kamu tidak memiliki akses ke panel ini.")
        if not is_staff(target):
            return await ctx.send("Member tujuan belum memiliki role Staff.")
        ticket = await find_or_create_staff_ticket(ctx.guild, target)
        _, created = await upsert_staff_panel(ticket, target)
        return await ctx.send(f"Staff Panel untuk {target.mention} {'dibuat' if created else 'diperbarui'} di {ticket.mention}.")
    await ctx.send("Kamu tidak memiliki akses ke panel ini.")

@bot.command(name="help-ryukomik")
async def help_command(ctx: commands.Context):
    """Show help for Ryukomik bot."""
    audience = "admin" if is_admin(ctx.author) else "staff" if is_staff(ctx.author) else "all"
    await ctx.send(embed=build_guide_embed(audience))


# ==================== ERROR HANDLING ====================

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Handle command errors."""
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("Ã¢ÂÅ’ Kamu tidak memiliki izin untuk menggunakan command ini!")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Ã¢ÂÅ’ Argument tidak valid!")
    else:
        print(f"Error: {error}")
        await ctx.send("Ã¢ÂÅ’ Terjadi error saat menjalankan command!")


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


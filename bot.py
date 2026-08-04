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
from recruitment.ticket import (
    RecruitmentApproveDynamic,
    RecruitmentView,
    setup_recruitment,
    upsert_recruitment_panel,
)
from raw_downloader import get_downloader
from helpers.utils import find_or_create_staff_ticket, is_admin, is_staff
from helpers.panel_content import build_admin_panel_embed, build_guide_embed, build_staff_panel_embed
from helpers.payrate_content import broadcast_payrate_update, upsert_payrate_panel
import payment_service as payments
import operations
from project_sync import setup_project_sync, sync_project_events
from views.payment_views import (
    ConfirmPayPayoutDynamic, IncomeMenuView, PayPayoutDynamic, PayoutAdminView, RejectPayoutDynamic,
    RetryInvoiceDynamic,
)
from views.role_views import ZodiacRoleView
from views.pair_views import (
    PairApproveDynamic, PairReviseDynamic, PairTlDynamic,
    PairStatusDynamic, PairTlRevisionChapterDynamic, PairTlRevisionDynamic,
    PairTsChapterDynamic, PairTsDynamic, publish_ts_handoff, refresh_project_panel,
)
import pair_workflow as pair_service
import project_scout as scout_service
import database as db
from server_management import apply_server_housekeeping, send_goodbye, send_welcome


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
        self.server_housekeeping_done = False
        self.recruitment_reconciled = False
        self.recruitment_panel_synced = False
        self.payrate_panel_synced = False
        self.pair_panels_reconciled = False
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        # Setup database
        await setup_database()
        await payments.setup_payment_tables()
        await operations.setup_operations()
        await scout_service.setup_scout_tables()
        await setup_project_sync()
        await operations.recover_outbox()
        
        # Add persistent views
        self.recruitment.register_persistent_views()
        self.add_view(AdminPanelView())
        self.add_view(StaffPanelView())
        self.add_view(IncomeMenuView())
        self.add_view(ZodiacRoleView())
        self.add_view(LegacyTaskView())
        self.add_dynamic_items(SubmitDynamicItem, ApproveDynamicItem, ReviseDynamicItem)
        self.add_dynamic_items(
            PairTlDynamic, PairTsDynamic, PairTlRevisionDynamic,
            PairTsChapterDynamic, PairTlRevisionChapterDynamic,
            PairStatusDynamic, PairApproveDynamic, PairReviseDynamic,
        )
        self.add_dynamic_items(RecruitmentApproveDynamic)
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
        if not notification_outbox_loop.is_running():
            notification_outbox_loop.start()
        if not project_event_sync_loop.is_running():
            project_event_sync_loop.start()
        if not daily_backup_loop.is_running():
            daily_backup_loop.start()
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

        if not self.server_housekeeping_done:
            try:
                target_guild = self.get_guild(GUILD_ID)
                if target_guild is not None:
                    await asyncio.wait_for(
                        apply_server_housekeeping(target_guild),
                        timeout=45,
                    )
                    self.server_housekeeping_done = True
                    print("[OK] Server housekeeping applied without changing layout", flush=True)
            except asyncio.TimeoutError:
                print("[ERROR] Server housekeeping timed out after 45 seconds", flush=True)
            except Exception as exc:
                print(f"[ERROR] Server housekeeping failed: {exc}", flush=True)

        if not self.recruitment_reconciled:
            try:
                target_guild = self.get_guild(GUILD_ID)
                if target_guild is not None:
                    moved = await self.recruitment.reconcile_legacy_reviews(target_guild)
                    self.recruitment_reconciled = True
                    print(f"[OK] Reconciled {moved} legacy recruitment review(s)", flush=True)
            except Exception as exc:
                print(f"[ERROR] Recruitment review reconciliation failed: {exc}", flush=True)

        if not self.recruitment_panel_synced:
            try:
                target_guild = self.get_guild(GUILD_ID)
                recruitment_channel = next(
                    (
                        channel
                        for channel in (target_guild.text_channels if target_guild else [])
                        if "staff-rekrutmen" in channel.name.casefold()
                        or "staff-recruitment" in channel.name.casefold()
                    ),
                    None,
                )
                if recruitment_channel is not None:
                    await upsert_recruitment_panel(recruitment_channel)
                    self.recruitment_panel_synced = True
                    print("[OK] Recruitment panel synchronized", flush=True)
            except Exception as exc:
                print(f"[ERROR] Recruitment panel synchronization failed: {exc}", flush=True)

        if not self.payrate_panel_synced:
            try:
                target_guild = self.get_guild(GUILD_ID)
                if target_guild is not None:
                    await upsert_payrate_panel(target_guild)
                    self.payrate_panel_synced = True
                    print("[OK] Staff payrate panel synchronized", flush=True)
            except Exception as exc:
                print(f"[ERROR] Payrate panel synchronization failed: {exc}", flush=True)

        if not self.pair_panels_reconciled:
            try:
                target_guild = self.get_guild(GUILD_ID)
                if target_guild is not None:
                    projects = await pair_service.list_projects()
                    for project in projects:
                        if project.get("channel_id") and project.get("panel_message_id"):
                            await refresh_project_panel(target_guild, int(project["id"]))
                        for chapter in project.get("chapters", []):
                            if chapter.get("status") in {"ready_for_ts", "ts_revision"} and chapter.get("tl_link"):
                                await publish_ts_handoff(target_guild, int(chapter["id"]))
                    self.pair_panels_reconciled = True
                    print(f"[OK] Synchronized {len(projects)} pair project panel(s)", flush=True)
            except Exception as exc:
                print(f"[ERROR] Pair panel synchronization failed: {exc}", flush=True)


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
                review_message_id = item.get("review_message_id")
                if review_message_id:
                    try:
                        message = await admin_channel.fetch_message(int(review_message_id))
                        embed = message.embeds[0] if message.embeds else discord.Embed()
                        existing = next(
                            (field for field in embed.fields if field.name == "Pengingat Review"),
                            None,
                        )
                        if not existing:
                            embed.add_field(
                                name="Pengingat Review",
                                value="⏳ Hasil ini sudah menunggu lebih dari 24 jam.",
                                inline=False,
                            )
                            embed.color = discord.Color.orange()
                            await message.edit(embed=embed)
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
                        await operations.record_event(
                            "review", "warning", "Card review tidak dapat diperbarui",
                            {"assignment_id": assignment_id, "error": str(error)[:300]},
                        )
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
            embed = discord.Embed(
                    title="⚠️ Tugas Melewati Deadline" if overdue else "⏰ Deadline Besok",
                    description=(
                        f"**#{assignment_id} — {item['manga']} Ch. {item['chapter']}**\n"
                        f"Deadline: **{deadline}**. "
                        + ("Gunakan **Bantuan Tugas** jika ada kendala." if overdue else "Pastikan hasil segera diselesaikan.")
                    ),
                    color=discord.Color.red() if overdue else discord.Color.gold(),
                )
            await operations.enqueue_notification(
                key, "deadline_reminder", ticket.id,
                {"content": member.mention if member else None, "embed": embed.to_dict()},
            )


@workflow_reminder_loop.before_loop
async def before_workflow_reminder_loop():
    await bot.wait_until_ready()


@tasks.loop(seconds=15)
async def notification_outbox_loop():
    started = datetime.now(ZoneInfo("Asia/Jakarta"))
    failure = None
    try:
        for item in await operations.due_notifications():
            try:
                channel = bot.get_channel(int(item["channel_id"]))
                if channel is None:
                    try:
                        channel = await bot.fetch_channel(int(item["channel_id"]))
                    except (discord.NotFound, discord.Forbidden):
                        channel = None
                if channel is None:
                    await operations.finish_notification(
                        item["id"], "Channel tidak ditemukan atau tidak dapat diakses.", permanent=True
                    )
                    continue
                import json
                payload = json.loads(item["payload_json"])
                embed = discord.Embed.from_dict(payload["embed"]) if payload.get("embed") else None
                await channel.send(content=payload.get("content"), embed=embed)
                await operations.finish_notification(item["id"])
            except (discord.NotFound, discord.Forbidden) as error:
                await operations.finish_notification(item["id"], error, permanent=True)
                await operations.record_event(
                    "discord", "error", "Notifikasi Discord gagal permanen",
                    {"outbox_id": item["id"], "error": str(error)[:300]},
                )
            except Exception as error:
                await operations.finish_notification(item["id"], error)
                await operations.record_event(
                    "discord", "warning", "Notifikasi Discord akan dicoba ulang",
                    {"outbox_id": item["id"], "error": str(error)[:300]},
                )
    except Exception as error:
        failure = error
        await operations.record_event("outbox", "error", "Worker outbox gagal", {"error": str(error)[:500]})
    finally:
        await operations.mark_scheduler("notification_outbox", started, failure)


@notification_outbox_loop.before_loop
async def before_notification_outbox_loop():
    await bot.wait_until_ready()


@tasks.loop(minutes=5)
async def project_event_sync_loop():
    """Deliver small project events; never poll the project catalogue or images."""
    started = datetime.now(ZoneInfo("Asia/Jakarta"))
    failure = None
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            return
        delivered = await sync_project_events(guild)
        if delivered:
            print(f"[PROJECT] Delivered {delivered} project event(s)", flush=True)
    except Exception as error:
        failure = str(error)[:500]
        print(f"[PROJECT] Event sync failed: {failure}", flush=True)
    finally:
        await operations.mark_scheduler("project_event_sync", started, failure)


@project_event_sync_loop.before_loop
async def before_project_event_sync_loop():
    await bot.wait_until_ready()


@tasks.loop(hours=1)
async def daily_backup_loop():
    now = datetime.now(ZoneInfo("Asia/Jakarta"))
    if now.hour != 3 or not await operations.daily_job_due("daily_backup", now.date().isoformat()):
        return
    failure = None
    try:
        await operations.create_verified_backup(payments.r2_client(), payments.R2_BUCKET_NAME)
    except Exception as error:
        failure = error
    finally:
        await operations.mark_scheduler("daily_backup", now, failure)


@daily_backup_loop.before_loop
async def before_daily_backup_loop():
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
    # Channel scans and panel updates can exceed Discord's three-second
    # acknowledgement window, so acknowledge before doing any I/O.
    await interaction.response.defer(ephemeral=False)

    if is_admin(interaction.user) and interaction.channel_id == STAFF_LOG_CHANNEL_ID:
        old_panel, _ = await upsert_admin_panel(interaction.channel)
        try:
            await old_panel.delete()
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.followup.send(
                "Panel tidak dapat dipindahkan. Pastikan bot memiliki izin **Manage Messages**; panel lama tetap tersedia melalui pesan pin.",
                ephemeral=False,
            )
        await interaction.followup.send("Panel administrator dipindahkan ke bawah.", ephemeral=False)
        await upsert_admin_panel(interaction.channel)
        return

    if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
        return await interaction.followup.send("Command ini hanya untuk staff atau administrator.", ephemeral=False)

    ticket = await find_or_create_staff_ticket(interaction.guild, interaction.user)
    if interaction.channel_id != ticket.id:
        return await interaction.followup.send(
            f"Gunakan `/menu` di tiket staff milikmu: {ticket.mention}", ephemeral=False
        )

    old_panel, _ = await upsert_staff_panel(ticket, interaction.user)
    try:
        await old_panel.delete()
    except (discord.Forbidden, discord.HTTPException):
        return await interaction.followup.send(
            "Panel tidak dapat dipindahkan. Pastikan bot memiliki izin **Manage Messages**; panel lama tetap tersedia melalui pesan pin.",
            ephemeral=False,
        )
    await interaction.followup.send("Panel kerjamu dipindahkan ke bawah.", ephemeral=False)
    await upsert_staff_panel(ticket, interaction.user)

@bot.tree.command(name="update-payrate", description="Ubah range payrate resmi staff")
@discord.app_commands.describe(
    role="Role TL, TS, atau TL+TS",
    min_rate="Rate minimum per chapter",
    max_rate="Rate maksimum per chapter",
)
async def update_payrate_command(
    interaction: discord.Interaction,
    role: Literal["TL", "TS", "TL+TS"],
    min_rate: int,
    max_rate: int,
):
    """Persist the official range and notify current staff tickets."""
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Hanya administrator yang dapat mengubah payrate.", ephemeral=False
        )

    normalized_role = role.strip().upper().replace(" ", "")
    if normalized_role not in ("TL", "TS", "TL+TS"):
        return await interaction.response.send_message(
            "Role harus TL, TS, atau TL+TS.", ephemeral=False
        )
    if min_rate < 0 or max_rate < min_rate or max_rate > 1_000_000:
        return await interaction.response.send_message(
            "Range tidak valid. Minimum harus ≤ maksimum dan maksimum paling besar Rp1.000.000.",
            ephemeral=False,
        )

    await interaction.response.defer(ephemeral=True)
    await db.set_role_payrate(normalized_role, min_rate, max_rate)
    await upsert_payrate_panel(interaction.guild)
    notified = await broadcast_payrate_update(
        interaction.guild, normalized_role, min_rate, max_rate
    )
    embed = discord.Embed(
        title="Payrate Berhasil Diperbarui",
        description=(
            f"Range **{normalized_role}** sekarang "
            f"**Rp {min_rate:,.0f} – Rp {max_rate:,.0f} / chapter**.\n"
            f"Notifikasi terkirim ke **{notified} tiket staff aktif**."
        ).replace(",", "."),
        color=discord.Color.green(),
    )
    embed.set_footer(text="Tugas lama dan manual override tidak berubah.")
    await interaction.followup.send(embed=embed, ephemeral=True)

async def search_manga_command(interaction: discord.Interaction, query: str, source: str = "asura"):
    """Search for manga on one validated RAW source."""
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
    filebin_url, completed, final_source = await create_filebin_download(source, manga_id, [chapter_id])
    if not filebin_url:
        return await interaction.followup.send(f"Gagal download atau upload ke Filebin dari **{source.title()}**. Coba lagi nanti.", ephemeral=False)
    embed = discord.Embed(title=f"RAW Siap Diunduh ({final_source.title()})", color=discord.Color.green())
    embed.add_field(name="Manga ID", value=manga_id, inline=True)
    embed.add_field(name="Chapter", value=", ".join(completed), inline=True)
    embed.add_field(name="Link Download", value=f"[Buka Filebin]({filebin_url})", inline=False)
    embed.set_footer(text="File lokal VPS sudah dihapus setelah upload.")
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="cari-project", description="Bandingkan judul RAW dengan katalog Indonesia")
@discord.app_commands.describe(judul="Judul komik RAW", sumber="Batasi sumber RAW atau cari di semua sumber")
async def scout_project_command(
    interaction: discord.Interaction,
    judul: str,
    sumber: Literal["all", "asura", "omega", "doujiva", "evascan", "thunder"] = "all",
):
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Project Scout hanya dapat digunakan Administrator.", ephemeral=True,
        )
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        result = await scout_service.scan_title(judul, sumber)
    except ValueError as error:
        return await interaction.followup.send(str(error), ephemeral=True)
    except Exception:
        return await interaction.followup.send(
            "Project Scout gagal menghubungi salah satu layanan. Coba lagi melalui dashboard.", ephemeral=True,
        )
    labels = {
        "untranslated": "Belum ditemukan di Indonesia", "lagging": "Versi Indonesia tertinggal",
        "available": "Sudah tersedia di Indonesia", "ambiguous": "Perlu diperiksa manual",
        "ryukomik_project": "Sudah menjadi project Ryukomik", "candidate": "Kandidat",
        "adopted": "Sudah diambil", "ignored": "Diabaikan",
    }
    embed = discord.Embed(
        title=f"Project Scout • {result['canonical_title']}",
        description=labels.get(result["scout_status"], result["scout_status"]),
        color=discord.Color.green() if result["scout_status"] == "untranslated" else discord.Color.gold(),
    )
    embed.add_field(name="Chapter RAW", value=str(result.get("raw_latest_chapter") or "—"), inline=True)
    embed.add_field(name="Chapter Indonesia", value=str(result.get("indonesia_latest_chapter") or "—"), inline=True)
    embed.add_field(name="Confidence", value=f"{result.get('confidence', 0)}%", inline=True)
    matches = [
        source for source in result.get("sources", [])
        if source.get("source_group") != "raw" and int(source.get("match_score") or 0) >= 55
    ][:6]
    embed.add_field(
        name="Hasil Pembanding",
        value="\n".join(
            f"• **{item['source'].title()}** — {item['title']} ({item['match_score']}%)" for item in matches
        ) or "Tidak ditemukan hasil yang cukup mirip.",
        inline=False,
    )
    embed.set_footer(text="Rekomendasi harus dikonfirmasi Administrator sebelum project diambil.")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="Buka Project Scout", style=discord.ButtonStyle.link,
        url=f"{DASHBOARD_URL}/?page=scout",
    ))
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="raw-search", description="Cari komik RAW dari semua sumber")
@discord.app_commands.describe(query="Judul atau kata kunci komik", source="Sumber RAW")
async def raw_search_command(interaction: discord.Interaction, query: str, source: Literal["asura", "omega", "doujiva", "evascan", "thunder"] = "asura"):
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
            health_query = "love" if source in {"omega", "evascan"} else "solo"
            result = await get_downloader(source).search_manga(health_query)
            return bool(result), round((time.perf_counter() - started) * 1000)
        except Exception:
            return False, round((time.perf_counter() - started) * 1000)

    database_status, asura_status, omega_status, doujiva_status, evascan_status, thunder_status = await asyncio.gather(check_db(), check_raw("asura"), check_raw("omega"), check_raw("doujiva"), check_raw("evascan"), check_raw("thunder"))
    embed = discord.Embed(title="Status Ryukomik Bot", description="Pemeriksaan langsung komponen utama.", color=discord.Color.green() if all(x[0] for x in (database_status, asura_status, omega_status, doujiva_status, evascan_status, thunder_status)) else discord.Color.orange())
    embed.add_field(name="Discord Gateway", value=f"Online • {round(bot.latency * 1000)} ms", inline=False)
    for name, result in (("Database", database_status), ("Asura API", asura_status), ("Omega API", omega_status), ("Doujiva API", doujiva_status), ("EvaScan API", evascan_status), ("Thunder API", thunder_status)):
        embed.add_field(name=name, value=f"{'Sehat' if result[0] else 'Bermasalah'} • {result[1]} ms")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="raw-chapters", description="Lihat daftar chapter RAW")
@discord.app_commands.describe(manga_id="Slug komik, contoh: love-cheer", source="Sumber RAW")
async def raw_chapters_command(interaction: discord.Interaction, manga_id: str, source: Literal["asura", "omega", "doujiva", "evascan", "thunder"] = "asura"):
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


@bot.tree.command(name="raw-download", description="Download chapter RAW dari sumber pilihan")
@discord.app_commands.describe(manga_id="Slug komik, contoh: lets-do-it-after-work", chapter_id="Nomor/slug chapter, contoh: 1", source="Sumber RAW")
async def raw_download_command(interaction: discord.Interaction, manga_id: str, chapter_id: str, source: Literal["asura", "omega", "doujiva", "evascan", "thunder"] = "asura"):
    await download_raw_command(interaction, manga_id, chapter_id, source)


@bot.tree.command(name="raw-download-batch", description="Batch download chapter RAW")
@discord.app_commands.describe(manga_id="Slug komik, contoh: lets-do-it-after-work", chapter_ids="Chapter dipisah koma, contoh: 1,2,3", source="Sumber RAW")
async def raw_download_batch_command(interaction: discord.Interaction, manga_id: str, chapter_ids: str, source: Literal["asura", "omega", "doujiva", "evascan", "thunder"] = "asura"):
    if not is_admin(interaction.user):
        return await interaction.response.send_message(
            "Batch RAW bebas hanya untuk administrator. Staff gunakan **Download RAW** pada Staff Panel.",
            ephemeral=True,
        )
    await interaction.response.defer(ephemeral=False)
    ids = [item.strip() for item in chapter_ids.split(",") if item.strip()][:10]
    if not ids:
        return await interaction.followup.send("Isi minimal satu chapter ID.", ephemeral=False)
    filebin_url, completed, final_source = await create_filebin_download(source, manga_id, ids)
    if not filebin_url:
        return await interaction.followup.send("Download atau upload Filebin gagal. Coba kembali nanti.")
    embed = discord.Embed(title=f"Batch RAW Siap Diunduh ({final_source.title()})", color=discord.Color.green())
    embed.add_field(name="Chapter Berhasil", value=", ".join(completed), inline=False)
    failed = [chapter for chapter in ids if chapter not in completed]
    if failed:
        embed.add_field(name="Chapter Gagal", value=", ".join(failed), inline=False)
    embed.add_field(name="Link Download", value=f"[Buka Filebin]({filebin_url})", inline=False)
    embed.set_footer(text="File lokal VPS sudah dihapus setelah upload.")
    await interaction.followup.send(embed=embed, ephemeral=False)


@bot.tree.command(name="raw-update", description="Cek update RAW terbaru")
@discord.app_commands.describe(query="Kata kunci komik (opsional)", source="Sumber RAW")
async def raw_update_command(interaction: discord.Interaction, query: str = "", source: Literal["asura", "omega", "doujiva", "evascan", "thunder"] = "asura"):
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


@bot.event
async def on_member_join(member: discord.Member):
    """Send one clear welcome card in the existing welcome channel."""
    if member.guild.id != GUILD_ID or member.bot:
        return
    try:
        await send_welcome(member)
    except discord.HTTPException as exc:
        print(f"[ERROR] Failed to send welcome for {member.id}: {exc}")


@bot.event
async def on_member_remove(member: discord.Member):
    """Send a compact goodbye card in the existing welcome channel."""
    if member.guild.id != GUILD_ID or member.bot:
        return
    try:
        await send_goodbye(member)
    except discord.HTTPException as exc:
        print(f"[ERROR] Failed to send goodbye for {member.id}: {exc}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Handle slash command errors."""
    print(f"Slash command error: {error}")
    message = "Terjadi error saat menjalankan slash command!"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=False)
        else:
            await interaction.response.send_message(message, ephemeral=False)
    except discord.NotFound:
        # The interaction token already expired; log the original failure
        # without raising a second Unknown Interaction traceback.
        print(f"[WARN] Could not report expired interaction {interaction.id}")


# ==================== RUN BOT ====================

if __name__ == "__main__":
    if not TOKEN:
        print("[ERROR] DISCORD_TOKEN tidak ditemukan di environment variables!")
        print("   Silakan buat file .env dan isi DISCORD_TOKEN")
        exit(1)
    
    bot.run(TOKEN)


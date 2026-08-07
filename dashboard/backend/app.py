import json
import os
import asyncio
import hashlib
import hmac
import re
from io import BytesIO
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Literal
import secrets
import time
import zipfile
from collections import defaultdict, deque
from pathlib import Path

import aiohttp
import aiosqlite
from PIL import Image, UnidentifiedImageError
try:
    import boto3
except ImportError:  # Legacy R2 downloads are optional in local/test environments.
    boto3 = None
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi.exceptions import RequestValidationError
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from config import (
    GUILD_ID,
    ROLE_ADMIN_ID,
    ROLE_STAFF_ID,
    REKRUT_CAT_ID,
    STAFF_LOG_CHANNEL_ID,
    STAFF_PAYRATE_CHANNEL_ID,
    TOKEN,
    RECRUITMENT_TEST_EXPIRES_AT,
    RECRUITMENT_TEST_URL,
    RECRUITMENT_TL_EXAMPLE_URL,
    RECRUITMENT_TS_ASSETS_URL,
)
import database as staff_db
import payment_service as payout_service
import performance_bonus as bonus_service
import operations
import pair_workflow as pair_service
import project_scout as scout_service
from database import DB_PATH, setup_database
from chapter_utils import chapter_display, parse_chapters
from invoice_pdf import render_paid_invoice
from raw_downloader import asura_downloader, doujiva_downloader, omega_downloader, evascan_downloader, thunder_downloader
from raw_downloader.resolver import resolve_assignment_raw
from raw_rate_analysis import RawWorkload, classify_workload, suggested_rate

# Shared deps (extracted to reduce app.py size)
from dashboard.backend.deps import (
    DASHBOARD_ORIGIN, API_ORIGIN, SESSION_SECRET,
    DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DEV_BYPASS,
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME, R2_ENDPOINT,
    TRAKTEER_WEBHOOK_TOKEN, TRAKTEER_TIP_URL, TRAKTEER_CHANNEL_NAME,
    _staff_cache, _staff_cache_lock,
    dashboard_db, DEFAULT_RATE_RANGES,
)

# Routers
from dashboard.backend.routers.tools import router as tools_router
from dashboard.backend.routers.assignments import router as assignments_router
from dashboard.backend.routers.invoices import router as invoices_router
from dashboard.backend.routers.payouts import router as payouts_router
from dashboard.backend.routers.bonus import router as bonus_router
from dashboard.backend.routers.scout import router as scout_router
from dashboard.backend.routers.pair import router as pair_router
from dashboard.backend.routers.recruitment import router as recruitment_router
from dashboard.backend.routers.staff import router as staff_router
from dashboard.backend.routers.payrate import router as payrate_router
from dashboard.backend.routers.operations import router as operations_router
from dashboard.backend.routers.notifications import router as notifications_router


async def setup_dashboard_tables():
    await pair_service.setup_pair_tables()
    await scout_service.setup_scout_tables()
    connection = await dashboard_db()
    try:
        await connection.execute("PRAGMA foreign_keys=OFF")
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS trakteer_events (
                transaction_id TEXT PRIMARY KEY,
                supporter_name TEXT NOT NULL,
                amount INTEGER NOT NULL,
                supporter_message TEXT,
                created_at TEXT NOT NULL,
                delivered_at DATETIME,
                discord_message_id TEXT
            )
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS recruitment_position_settings (
                position TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT
            )
        """)
        await connection.executemany(
            "INSERT OR IGNORE INTO recruitment_position_settings(position,enabled) VALUES(?,1)",
            (("TL",), ("TS",), ("TL+TS",)),
        )
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS recruitment_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                applicant_id INTEGER NOT NULL,
                position TEXT NOT NULL,
                ticket_channel_id INTEGER NOT NULL,
                gdrive_link TEXT NOT NULL,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'submitted',
                review_message_id INTEGER,
                submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                reviewed_at DATETIME,
                reviewed_by INTEGER
            )
        """)
        payrate_columns = {
            row["name"]
            for row in await (await connection.execute("PRAGMA table_info(payrates)")).fetchall()
        }
        if payrate_columns:
            migrate_ranges = "min_rate" not in payrate_columns
            if "min_rate" not in payrate_columns:
                await connection.execute("ALTER TABLE payrates ADD COLUMN min_rate INTEGER")
            if "max_rate" not in payrate_columns:
                await connection.execute("ALTER TABLE payrates ADD COLUMN max_rate INTEGER")
            if migrate_ranges:
                await connection.executemany(
                    "UPDATE payrates SET base_rate=?,min_rate=?,max_rate=? WHERE role=?",
                    (
                        (4000, 4000, 8000, "TL"),
                        (5000, 5000, 10000, "TS"),
                        (9000, 9000, 18000, "TL+TS"),
                    ),
                )
            else:
                await connection.execute(
                    "UPDATE payrates SET min_rate=COALESCE(min_rate,base_rate), max_rate=COALESCE(max_rate,base_rate)"
                )
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT,
                before_data TEXT,
                after_data TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT NOT NULL UNIQUE,
                staff_id INTEGER NOT NULL,
                period TEXT NOT NULL,
                chapter_count INTEGER NOT NULL,
                total_amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'issued',
                issued_by INTEGER NOT NULL,
                issued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                paid_at DATETIME,
                invoice_type TEXT NOT NULL DEFAULT 'standard',
                parent_invoice_id INTEGER,
                revised_at DATETIME,
                revised_by INTEGER,
                voided_at DATETIME,
                voided_by INTEGER
            )
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                assignment_id INTEGER NOT NULL,
                manga TEXT NOT NULL,
                chapter TEXT NOT NULL,
                role TEXT NOT NULL,
                amount INTEGER NOT NULL,
                assigned_at DATETIME,
                approved_at DATETIME,
                chapter_count INTEGER NOT NULL DEFAULT 1,
                rate_per_chapter INTEGER,
                UNIQUE(invoice_id, assignment_id),
                FOREIGN KEY(invoice_id) REFERENCES dashboard_invoices(id)
            )
        """)
        item_columns = {row["name"] for row in await (await connection.execute(
            "PRAGMA table_info(dashboard_invoice_items)"
        )).fetchall()}
        if "chapter_count" not in item_columns:
            await connection.execute("ALTER TABLE dashboard_invoice_items ADD COLUMN chapter_count INTEGER NOT NULL DEFAULT 1")
        if "rate_per_chapter" not in item_columns:
            await connection.execute("ALTER TABLE dashboard_invoice_items ADD COLUMN rate_per_chapter INTEGER")
        await connection.execute("""
            UPDATE dashboard_invoice_items
            SET chapter_count=COALESCE(NULLIF(chapter_count,0),1),
                rate_per_chapter=COALESCE(rate_per_chapter,amount)
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_staff_cache (
                staff_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                avatar TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS assignment_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                staff_id INTEGER NOT NULL,
                object_key TEXT NOT NULL UNIQUE,
                original_name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                uploaded_at DATETIME,
                FOREIGN KEY(assignment_id) REFERENCES assignments(id)
            )
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_schema_migrations (
                version INTEGER PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        invoice_sql_row = await (await connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='dashboard_invoices'"
        )).fetchone()
        if invoice_sql_row and "UNIQUE(staff_id, period)" in (invoice_sql_row["sql"] or ""):
            await connection.executescript("""
                CREATE TABLE dashboard_invoices_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_number TEXT NOT NULL UNIQUE,
                    staff_id INTEGER NOT NULL, period TEXT NOT NULL, chapter_count INTEGER NOT NULL,
                    total_amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'issued', issued_by INTEGER NOT NULL,
                    issued_at DATETIME DEFAULT CURRENT_TIMESTAMP, paid_at DATETIME,
                    invoice_type TEXT NOT NULL DEFAULT 'standard', parent_invoice_id INTEGER,
                    revised_at DATETIME, revised_by INTEGER, voided_at DATETIME, voided_by INTEGER
                );
                INSERT INTO dashboard_invoices_v2
                    (id,invoice_number,staff_id,period,chapter_count,total_amount,status,issued_by,issued_at,paid_at)
                SELECT id,invoice_number,staff_id,period,chapter_count,total_amount,status,issued_by,issued_at,paid_at
                FROM dashboard_invoices;
                DROP TABLE dashboard_invoices;
                ALTER TABLE dashboard_invoices_v2 RENAME TO dashboard_invoices;
            """)
        columns = {row["name"] for row in await (await connection.execute("PRAGMA table_info(dashboard_invoices)")).fetchall()}
        for name, definition in (
            ("invoice_type", "TEXT NOT NULL DEFAULT 'standard'"),
            ("parent_invoice_id", "INTEGER"),
            ("revised_at", "DATETIME"), ("revised_by", "INTEGER"),
            ("voided_at", "DATETIME"), ("voided_by", "INTEGER"),
        ):
            if name not in columns:
                await connection.execute(f"ALTER TABLE dashboard_invoices ADD COLUMN {name} {definition}")
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_assignment_billing (
                assignment_id INTEGER PRIMARY KEY,
                invoice_id INTEGER NOT NULL,
                FOREIGN KEY(invoice_id) REFERENCES dashboard_invoices(id)
            )
        """)
        await connection.execute("""
            INSERT OR IGNORE INTO dashboard_assignment_billing(assignment_id, invoice_id)
            SELECT i.assignment_id, i.invoice_id FROM dashboard_invoice_items i
            JOIN dashboard_invoices v ON v.id=i.invoice_id WHERE v.status!='void'
        """)
        await connection.execute("INSERT OR IGNORE INTO dashboard_schema_migrations(version) VALUES(2)")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_invoices_period_status ON dashboard_invoices(period,status)")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON dashboard_audit_logs(created_at)")
        await connection.commit()
        await connection.execute("PRAGMA foreign_keys=ON")
    finally:
        await connection.close()
    await operations.setup_operations()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await setup_database()
    await setup_dashboard_tables()
    await bonus_service.setup_tables()
    await payout_service.setup_payment_tables()
    yield


app = FastAPI(title="Ryukomik Staff Dashboard API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET or "development-only-change-me",
    https_only=not DEV_BYPASS,
    same_site="lax",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[DASHBOARD_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

# Include routers (auth stays in app.py — uses local helpers)
app.include_router(tools_router)
app.include_router(assignments_router)
app.include_router(invoices_router)
app.include_router(payouts_router)
app.include_router(bonus_router)
app.include_router(scout_router)
app.include_router(pair_router)
app.include_router(recruitment_router)
app.include_router(staff_router)
app.include_router(payrate_router)
app.include_router(operations_router)
app.include_router(notifications_router)

_rate_windows: dict[str, deque] = defaultdict(deque)
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    content_length = int(request.headers.get("content-length", "0") or 0)
    # Converter needs larger uploads (images can be 50MB+)
    max_size = 200 * 1024 * 1024 if request.url.path.startswith("/api/tools/") else 2 * 1024 * 1024
    if content_length > max_size:
        return JSONResponse({"detail": "Ukuran request melebihi batas."}, status_code=413)
    if request.method in MUTATING_METHODS:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != DASHBOARD_ORIGIN:
            return JSONResponse({"detail": "Origin request tidak diizinkan."}, status_code=403)
    category = "login" if request.url.path.startswith("/auth/") else "mutation" if request.method in MUTATING_METHODS else "read"
    limit = 10 if category == "login" else 60 if category == "mutation" else 300
    key = f"{request.client.host if request.client else 'unknown'}:{category}"
    now = time.monotonic()
    window = _rate_windows[key]
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= limit:
        return JSONResponse({"detail": "Terlalu banyak request. Coba lagi sebentar."}, status_code=429)
    window.append(now)
    try:
        response = await call_next(request)
    except HTTPException:
        raise
    except Exception:
        return JSONResponse({"detail": "Terjadi kesalahan internal."}, status_code=500)
    response.headers.update({
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Referrer-Policy": "same-origin", "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; script-src 'self'",
    })
    return response

oauth = OAuth()
if DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET:
    oauth.register(
        name="discord",
        client_id=DISCORD_CLIENT_ID,
        client_secret=DISCORD_CLIENT_SECRET,
        authorize_url="https://discord.com/oauth2/authorize",
        access_token_url="https://discord.com/api/oauth2/token",
        api_base_url="https://discord.com/api/",
        client_kwargs={"scope": "identify"},
    )


async def fetch_member(user_id: int):
    if not TOKEN:
        return None
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}",
            headers={"Authorization": f"Bot {TOKEN}"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            return await response.json() if response.status == 200 else None


def role_from_member(member: dict):
    roles = {int(role_id) for role_id in member.get("roles", [])}
    if ROLE_ADMIN_ID in roles:
        return "admin"
    if ROLE_STAFF_ID in roles:
        return "staff"
    return None


async def current_user(request: Request):
    if DEV_BYPASS:
        request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
        user = {"id": 1, "username": "Development Admin", "avatar": None, "role": "admin"}
        if request.method in MUTATING_METHODS and not secrets.compare_digest(
            request.headers.get("x-csrf-token", ""), request.session["csrf_token"]
        ):
            raise HTTPException(status_code=403, detail="Token keamanan tidak valid. Muat ulang dashboard.")
        return user
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Silakan masuk dengan Discord.")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Dashboard hanya tersedia untuk administrator.")
    request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
    if request.method in MUTATING_METHODS and not secrets.compare_digest(
        request.headers.get("x-csrf-token", ""), request.session["csrf_token"]
    ):
        raise HTTPException(status_code=403, detail="Token keamanan tidak valid. Muat ulang dashboard.")
    return user


async def admin_user(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Hanya administrator yang dapat melakukan tindakan ini.")
    return user


async def audit(actor_id, action, target_type, target_id=None, before=None, after=None):
    connection = await dashboard_db()
    try:
        await connection.execute(
            """INSERT INTO dashboard_audit_logs
               (actor_id, action, target_type, target_id, before_data, after_data)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (actor_id, action, target_type, str(target_id) if target_id else None,
             json.dumps(before, default=str) if before is not None else None,
             json.dumps(after, default=str) if after is not None else None),
        )
        await connection.commit()
    finally:
        await connection.close()


class PayrateUpdate(BaseModel):
    min_rate: int | None = Field(default=None, ge=0, le=1_000_000)
    max_rate: int | None = Field(default=None, ge=0, le=1_000_000)
    base_rate: int | None = Field(default=None, ge=0, le=1_000_000)


class RecruitmentSettingsUpdate(BaseModel):
    tl: bool
    ts: bool
    tl_ts: bool

class RecruitmentCloseRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AssignmentCreate(BaseModel):
    manga: str = Field(min_length=2, max_length=150)
    chapter: str = Field(min_length=1, max_length=30)
    staff_id: str
    role: Literal["TL", "TS", "TL+TS"]
    rate_per_chapter: int | None = Field(default=None, ge=0, le=1_000_000)
    final_rate: int | None = Field(default=None, ge=0, le=1_000_000)
    deadline_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class TlTsPairCreate(BaseModel):
    manga: str = Field(min_length=2, max_length=150)
    chapter: str = Field(min_length=1, max_length=30)
    tl_staff_id: str
    ts_staff_id: str
    tl_rate_per_chapter: int = Field(ge=0, le=1_000_000)
    ts_rate_per_chapter: int = Field(ge=0, le=1_000_000)
    deadline_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class AssignmentUpdate(BaseModel):
    manga: str = Field(min_length=2, max_length=150)
    chapter: str = Field(min_length=1, max_length=30)
    role: Literal["TL", "TS", "TL+TS"]
    rate_per_chapter: int = Field(ge=0, le=1_000_000)
    deadline_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class RawRateAnalysisRequest(BaseModel):
    manga: str = Field(min_length=2, max_length=150)
    chapter: str = Field(min_length=1, max_length=30)
    role: Literal["TL", "TS", "TL+TS"]


class ScoutSearchRequest(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    raw_source: Literal["all", "asura", "omega", "doujiva", "evascan", "thunder"] = "all"
    force: bool = False


class ScoutDecisionRequest(BaseModel):
    action: Literal["candidate", "adopt", "available", "ignore", "ambiguous"]
    notes: str = Field(default="", max_length=1000)


class InvoiceCreate(BaseModel):
    staff_id: str
    period: str = Field(pattern=r"^\d{4}-\d{2}$")


class RevisionRequest(BaseModel):
    notes: str = Field(min_length=3, max_length=1500)


class PayoutRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class PayoutPayConfirmRequest(BaseModel):
    amount: int = Field(gt=0)
    destination_last4: str = Field(pattern=r"^[0-9A-Za-z]{4}$")


class BonusSettingsUpdate(BaseModel):
    quality_weight: int = Field(ge=0, le=100)
    speed_weight: int = Field(ge=0, le=100)
    consistency_weight: int = Field(ge=0, le=100)
    min_chapters: int = Field(ge=1, le=100)
    tier_1_score: int = Field(ge=0, le=100)
    tier_1_percent: int = Field(ge=0, le=100)
    tier_2_score: int = Field(ge=0, le=100)
    tier_2_percent: int = Field(ge=0, le=100)
    tier_3_score: int = Field(ge=0, le=100)
    tier_3_percent: int = Field(ge=0, le=100)
    max_amount: int = Field(ge=0, le=10_000_000)


class BonusRunRequest(BaseModel):
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class BonusRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


from pydantic import BaseModel, Field, field_validator

class ManualBonusCreateRequest(BaseModel):
    staff_id: str = Field(min_length=1)
    amount: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)
    period: str | None = Field(default=None)

    @field_validator("staff_id", mode="before")
    @classmethod
    def coerce_staff_id(cls, v):
        return str(v)


class OperationAction(BaseModel):
    id: int = Field(gt=0)


class UploadRequest(BaseModel):
    assignment_id: int
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = Field(default="application/zip", max_length=100)
    size_bytes: int = Field(gt=0, le=5 * 1024 * 1024 * 1024)


def r2_client():
    if not all((R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME)):
        raise HTTPException(status_code=503, detail="Penyimpanan R2 belum dikonfigurasi.")
    if boto3 is None:
        raise HTTPException(status_code=503, detail="Dukungan arsip R2 tidak terpasang.")
    return boto3.client("s3", endpoint_url=R2_ENDPOINT, aws_access_key_id=R2_ACCESS_KEY_ID,
                        aws_secret_access_key=R2_SECRET_ACCESS_KEY, region_name="auto")


def safe_object_part(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    return "-".join(filter(None, cleaned.split("-")))[:80] or "file"


async def discord_api(method: str, path: str, payload=None):
    if not TOKEN:
        return None
    async with aiohttp.ClientSession() as session:
        async with session.request(
            method,
            f"https://discord.com/api/v10{path}",
            headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if 200 <= response.status < 300:
                if response.status == 204:
                    return {}
                try:
                    return await response.json()
                except (aiohttp.ContentTypeError, json.JSONDecodeError):
                    return {}
            return None


def pair_panel_payload(project: dict) -> dict:
    state_labels = {
        "waiting_tl": "Menunggu TL", "ready_for_ts": "Siap TS",
        "tl_revision": "Perbaikan TL", "ts_revision": "Perbaikan TS",
        "both_revision": "Perbaikan TL + TS", "final_review": "Review Final",
        "completed": "Selesai",
    }
    progress = "\n".join(
        f"{'✅' if item['status'] == 'completed' else '🔄' if 'revision' in item['status'] else '•'} "
        f"**Chapter {item['chapter']}** — {state_labels.get(item['status'], item['status'])}"
        for item in project["chapters"]
    )
    return {
        "embeds": [{
            "title": f"Kolaborasi TL–TS • {project['manga']}",
            "description": (
                f"<@{project['tl_staff_id']}> sebagai **Translator** dan <@{project['ts_staff_id']}> "
                "sebagai **Typesetter** bekerja dalam satu ruang.\n"
                "Gaji setiap chapter dilepas untuk keduanya setelah hasil final disetujui Administrator."
            ),
            "color": 6253567,
            "fields": [
                {"name": "Progress", "value": progress, "inline": False},
                {"name": "Rate TL", "value": f"Rp {project['tl_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Rate TS", "value": f"Rp {project['ts_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Deadline", "value": project.get("deadline_at") or "Tidak ditentukan", "inline": True},
            ],
            "footer": {"text": f"Pair Project #{project['id']} • Gunakan tombol sesuai peran"},
        }],
        "components": [{"type": 1, "components": [
            {"type": 2, "style": 1, "label": "Submit Hasil TL", "custom_id": f"pair:tl:{project['id']}:v2"},
            {"type": 2, "style": 3, "label": "Submit Final TS", "custom_id": f"pair:ts:{project['id']}:v2"},
            {"type": 2, "style": 4, "label": "Minta Perbaikan TL", "custom_id": f"pair:tl-revision:{project['id']}:v2"},
            {"type": 2, "style": 2, "label": "Lihat Status Chapter", "custom_id": f"pair:status:{project['id']}:v2"},
            {"type": 2, "style": 2, "label": "Download RAW", "custom_id": f"pair:raw:{project['id']}:v2"},
        ]}],
        "allowed_mentions": {"users": [str(project["tl_staff_id"]), str(project["ts_staff_id"])]},
    }


async def create_pair_workspace(project_id: int) -> tuple[str, str]:
    project = await pair_service.get_project(project_id)
    if not project:
        raise RuntimeError("Pair project tidak ditemukan setelah dibuat.")
    reusable = await pair_service.find_reusable_workspace(project["manga"])
    channel = None
    created_new_channel = False
    if reusable:
        channel = await discord_api("GET", f"/channels/{reusable['channel_id']}")
    if channel:
        slug = re.sub(r"[^a-z0-9]+", "-", project["manga"].casefold()).strip("-")[:70] or "project"
        await discord_api("PATCH", f"/channels/{channel['id']}", {
            "name": f"🔒・project-{slug}",
            "topic": f"Ruang permanen {project['manga']} | Pair aktif #{project_id} | TL:{project['tl_staff_id']} | TS:{project['ts_staff_id']}",
        })
        staff_allow = str((1 << 10) | (1 << 11) | (1 << 14) | (1 << 15) | (1 << 16))
        for staff_id in {str(project["tl_staff_id"]), str(project["ts_staff_id"])}:
            await discord_api("PUT", f"/channels/{channel['id']}/permissions/{staff_id}", {
                "type": 1, "allow": staff_allow, "deny": "0",
            })
        current_staff = {str(project["tl_staff_id"]), str(project["ts_staff_id"])}
        for overwrite in channel.get("permission_overwrites", []):
            overwrite_id = str(overwrite.get("id") or "")
            if int(overwrite.get("type", 0)) == 1 and overwrite_id not in current_staff:
                await discord_api("DELETE", f"/channels/{channel['id']}/permissions/{overwrite_id}")
        await discord_api("PUT", f"/channels/{channel['id']}/permissions/{ROLE_STAFF_ID}", {
            "type": 0, "allow": "0", "deny": str(1 << 10),
        })
        if reusable.get("panel_message_id"):
            await discord_api("DELETE", f"/channels/{channel['id']}/pins/{reusable['panel_message_id']}")
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", project["manga"].casefold()).strip("-")[:70] or "project"
        staff_allow = str((1 << 10) | (1 << 11) | (1 << 14) | (1 << 15) | (1 << 16))
        admin_allow = str(int(staff_allow) | (1 << 4) | (1 << 13))
        channel = await discord_api("POST", f"/guilds/{GUILD_ID}/channels", {
        "name": f"🔒・project-{slug}",
        "type": 0,
        "parent_id": str(REKRUT_CAT_ID),
        "topic": f"Ruang permanen {project['manga']} | Pair aktif #{project_id} | TL:{project['tl_staff_id']} | TS:{project['ts_staff_id']}",
        "permission_overwrites": [
            {"id": str(GUILD_ID), "type": 0, "deny": str(1 << 10), "allow": "0"},
            {"id": str(ROLE_STAFF_ID), "type": 0, "deny": str(1 << 10), "allow": "0"},
            {"id": str(project["tl_staff_id"]), "type": 1, "allow": staff_allow, "deny": "0"},
            {"id": str(project["ts_staff_id"]), "type": 1, "allow": staff_allow, "deny": "0"},
            {"id": str(ROLE_ADMIN_ID), "type": 0, "allow": admin_allow, "deny": "0"},
        ],
        })
        if not channel:
            raise RuntimeError("Discord gagal membuat channel proyek privat.")
        created_new_channel = True
    message = await discord_api("POST", f"/channels/{channel['id']}/messages", {
        "content": f"<@{project['tl_staff_id']}> <@{project['ts_staff_id']}> ruang kolaborasi kalian sudah siap.",
        **pair_panel_payload(project),
    })
    if not message:
        if created_new_channel:
            await discord_api("DELETE", f"/channels/{channel['id']}")
        raise RuntimeError("Discord gagal membuat panel pair.")
    await discord_api("PUT", f"/channels/{channel['id']}/pins/{message['id']}")
    await pair_service.set_workspace(project_id, int(channel["id"]), int(message["id"]))
    if reusable and str(reusable["channel_id"]) == str(channel["id"]):
        await pair_service.record_workspace_reuse(project_id, int(reusable["id"]))
    return str(channel["id"]), str(message["id"])


async def refresh_pair_workspace_rest(project_id: int) -> None:
    project = await pair_service.get_project(project_id)
    if not project or not project.get("channel_id") or not project.get("panel_message_id") or DEV_BYPASS:
        return
    await discord_api(
        "PATCH", f"/channels/{project['channel_id']}/messages/{project['panel_message_id']}",
        pair_panel_payload(project),
    )


async def remove_pair_review_rest(chapter: dict) -> None:
    if chapter.get("review_message_id") and not DEV_BYPASS:
        await discord_api("DELETE", f"/channels/{STAFF_LOG_CHANNEL_ID}/messages/{chapter['review_message_id']}")
    await pair_service.set_review_message(int(chapter["id"]), None)


async def complete_pair_review_rest(chapter: dict) -> None:
    if not chapter.get("review_message_id") or DEV_BYPASS:
        return
    await discord_api(
        "PATCH", f"/channels/{STAFF_LOG_CHANNEL_ID}/messages/{chapter['review_message_id']}",
        {"embeds": [{
            "title": f"✅ Pair Selesai • {chapter['manga']} Chapter {chapter['chapter']}",
            "description": "Hasil final disetujui. Gaji TL dan TS masuk ke saldo secara bersamaan.",
            "color": 5763719,
            "fields": [
                {"name": "Translator", "value": f"<@{chapter['tl_staff_id']}> • Rp {chapter['tl_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Typesetter", "value": f"<@{chapter['ts_staff_id']}> • Rp {chapter['ts_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Hasil TL", "value": chapter.get("tl_link") or "Tidak tersedia", "inline": False},
                {"name": "Hasil Final", "value": chapter.get("final_link") or "Tidak tersedia", "inline": False},
            ],
        }], "components": []},
    )


async def trakteer_channel_id() -> str | None:
    """Resolve the existing appreciation channel without storing a webhook URL."""
    channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels")
    if not isinstance(channels, list):
        return None
    for channel in channels:
        channel_name = str(channel.get("name", "")).casefold()
        if channel.get("type") == 0 and TRAKTEER_CHANNEL_NAME in channel_name:
            return str(channel["id"])
    return None


def donation_text(value: object, limit: int) -> str:
    """Keep donor text readable but prevent mass mentions or oversized embeds."""
    return str(value or "").strip().replace("@", "@\u200b")[:limit]


@app.post("/webhooks/trakteer")
async def trakteer_webhook(request: Request):
    """Receive verified Trakteer tips and publish one idempotent Discord card."""
    supplied_token = request.headers.get("X-Webhook-Token", "")
    if not TRAKTEER_WEBHOOK_TOKEN or not hmac.compare_digest(supplied_token, TRAKTEER_WEBHOOK_TOKEN):
        raise HTTPException(status_code=401, detail="Webhook token tidak valid.")
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Payload webhook tidak valid.")
    if not isinstance(payload, dict) or payload.get("type") != "tip":
        return {"ok": True, "ignored": True}
    transaction_id = donation_text(payload.get("transaction_id"), 160)
    if not transaction_id:
        raise HTTPException(status_code=400, detail="ID transaksi tidak ditemukan.")
    try:
        amount = max(0, int(float(payload.get("price") or 0)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Nominal transaksi tidak valid.")
    supporter = donation_text(payload.get("supporter_name") or "Supporter Ryukomik", 100)
    message = donation_text(payload.get("supporter_message"), 900)
    created_at = donation_text(payload.get("created_at"), 64)
    connection = await dashboard_db()
    try:
        await connection.execute(
            """INSERT OR IGNORE INTO trakteer_events
               (transaction_id,supporter_name,amount,supporter_message,created_at)
               VALUES(?,?,?,?,?)""",
            (transaction_id, supporter, amount, message or None, created_at),
        )
        row = await (await connection.execute(
            "SELECT delivered_at FROM trakteer_events WHERE transaction_id=?", (transaction_id,)
        )).fetchone()
        await connection.commit()
    finally:
        await connection.close()
    if row and row["delivered_at"]:
        return {"ok": True, "duplicate": True}
    channel_id = await trakteer_channel_id()
    if not channel_id:
        raise HTTPException(status_code=503, detail="Channel apresiasi-staff tidak ditemukan.")
    embed = {
        "title": "💜 Terima Kasih atas Dukunganmu!",
        "description": f"**{supporter}** baru saja memberi dukungan untuk Ryukomik.",
        "color": 0x8B5CF6,
        "fields": [
            {"name": "Dukungan", "value": f"Rp {amount:,.0f}".replace(",", "."), "inline": True},
            {"name": "Donasi", "value": f"[Dukung Ryukomik di Trakteer]({TRAKTEER_TIP_URL})", "inline": True},
        ],
        "footer": {"text": "Ryukomik Official • Terima kasih sudah mendukung karya kami"},
    }
    if message:
        embed["fields"].append({"name": "Pesan Supporter", "value": message, "inline": False})
    sent = await discord_api("POST", f"/channels/{channel_id}/messages", {
        "embeds": [embed],
        "components": [{"type": 1, "components": [{"type": 2, "style": 5, "label": "Dukung di Trakteer", "url": TRAKTEER_TIP_URL}]}],
        "allowed_mentions": {"parse": []},
    })
    if not sent:
        raise HTTPException(status_code=503, detail="Notifikasi Discord gagal dikirim.")
    connection = await dashboard_db()
    try:
        await connection.execute(
            "UPDATE trakteer_events SET delivered_at=CURRENT_TIMESTAMP,discord_message_id=? WHERE transaction_id=?",
            (str(sent.get("id") or ""), transaction_id),
        )
        await connection.commit()
    finally:
        await connection.close()
    return {"ok": True}


def discord_avatar(member: dict) -> str | None:
    user = member.get("user", {})
    avatar = member.get("avatar") or user.get("avatar")
    if not avatar:
        return None
    if member.get("avatar"):
        return f"https://cdn.discordapp.com/guilds/{GUILD_ID}/users/{user['id']}/avatars/{avatar}.png?size=128"
    return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png?size=128"


def resolve_staff_id(staff_id: str, profiles: dict) -> str | None:
    if staff_id in profiles:
        return staff_id
    for pid in profiles:
        if pid[:14] == staff_id[:14]:
            return pid
    return None


async def resolve_staff_id_with_fallback(staff_id: str, profiles: dict) -> str | None:
    """Seperti resolve_staff_id, tapi kalau tidak ditemukan di direktori Discord,
    cek dashboard_staff_cache DB sebagai fallback. Ini mengatasi kondisi di mana
    cache direktori expired dan Discord API mengembalikan data segar yang mungkin
    belum mencerminkan perubahan role, atau saat ada race condition antara
    dropdown (in-memory cache) dan validasi saat submit."""
    result = resolve_staff_id(staff_id, profiles)
    if result:
        return result
    # Fallback: cek dashboard_staff_cache DB
    connection = await dashboard_db()
    try:
        row = await (await connection.execute(
            "SELECT staff_id FROM dashboard_staff_cache WHERE staff_id=?",
            (staff_id,),
        )).fetchone()
        if row:
            return str(row[0])
        # Partial match (14 karakter pertama)
        row = await (await connection.execute(
            "SELECT staff_id FROM dashboard_staff_cache WHERE SUBSTR(staff_id,1,14)=?",
            (staff_id[:14],),
        )).fetchone()
        if row:
            return str(row[0])
    finally:
        await connection.close()
    return None

def member_profile(member: dict):
    discord_user = member.get("user", {})
    if not discord_user.get("id"):
        return None
    return {"id": str(discord_user["id"]), "username": member.get("nick") or discord_user.get("global_name") or discord_user.get("username", "Staff"), "avatar": discord_avatar(member)}


async def cache_staff_profile(profile: dict):
    connection = await dashboard_db()
    try:
        await connection.execute("""
            INSERT INTO dashboard_staff_cache(staff_id,username,avatar,updated_at)
            VALUES(?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(staff_id) DO UPDATE SET username=excluded.username,
                avatar=excluded.avatar, updated_at=CURRENT_TIMESTAMP
        """, (profile["id"], profile["username"], profile.get("avatar")))
        await connection.commit()
    finally:
        await connection.close()


async def staff_directory(force=False):
    if DEV_BYPASS:
        connection = await dashboard_db()
        try:
            rows = await (await connection.execute(
                "SELECT DISTINCT staff_id FROM assignments WHERE staff_id IS NOT NULL"
            )).fetchall()
            return [{"id": str(row[0]), "username": f"Staff {row[0]}", "avatar": None} for row in rows]
        finally:
            await connection.close()
    if not force and _staff_cache["items"] and time.monotonic() < _staff_cache["expires_at"]:
        return _staff_cache["items"]
    async with _staff_cache_lock:
        if not force and _staff_cache["items"] and time.monotonic() < _staff_cache["expires_at"]:
            return _staff_cache["items"]
        connection = await dashboard_db()
        try:
            cached = await (await connection.execute("SELECT staff_id id, username, avatar FROM dashboard_staff_cache")).fetchall()
            known = await (await connection.execute("SELECT DISTINCT staff_id FROM assignments WHERE staff_id IS NOT NULL")).fetchall()
        finally:
            await connection.close()
        profiles = {row["id"]: dict(row) for row in cached}
        members = await discord_api("GET", f"/guilds/{GUILD_ID}/members?limit=1000")
        if members is None and profiles:
            result = sorted(profiles.values(), key=lambda item: item["username"].casefold())
            _staff_cache.update(items=result, expires_at=time.monotonic() + 120, updated_at=datetime.now().isoformat())
            return result
        if members is not None:
            profiles = {}
        for member in members or []:
            roles = {int(role) for role in member.get("roles", [])}
            if ROLE_STAFF_ID not in roles:
                continue
            profile = member_profile(member)
            if profile:
                profiles[profile["id"]] = profile
        for row in known:
            if row["staff_id"] in profiles:
                continue
            profile = member_profile(await fetch_member(row["staff_id"]) or {})
            if profile:
                profiles[profile["id"]] = profile
        for profile in profiles.values():
            await cache_staff_profile(profile)
        result = sorted(profiles.values(), key=lambda item: item["username"].casefold())
        _staff_cache.update(items=result, expires_at=time.monotonic() + 600, updated_at=datetime.now().isoformat())
        return result


async def enrich_staff(rows):
    profiles = {str(item["id"]): item for item in await staff_directory()}
    enriched = []
    for row in rows:
        item = dict(row)
        profile = profiles.get(str(item.get("staff_id")), {})
        item["staff_name"] = profile.get("username") or f"Staff {item.get('staff_id') or 'belum dipilih'}"
        item["staff_avatar"] = profile.get("avatar")
        if item.get("staff_id") is not None:
            item["staff_id"] = str(item["staff_id"])
        enriched.append(item)
    return enriched


async def role_rate_range(role: str) -> tuple[int, int]:
    connection = await dashboard_db()
    try:
        row = await (await connection.execute(
            "SELECT base_rate,min_rate,max_rate FROM payrates WHERE role=?",
            (role,),
        )).fetchone()
    finally:
        await connection.close()
    default_min, default_max = DEFAULT_RATE_RANGES[role]
    if not row:
        return default_min, default_max
    return (
        int(row["min_rate"] or row["base_rate"] or default_min),
        int(row["max_rate"] or default_max),
    )


def payrate_embed_payload(ranges: dict[str, tuple[int, int]]) -> dict:
    labels = {
        "TL": "Translator (TL)",
        "TS": "Editor / Typesetter (TS)",
        "TL+TS": "TL + TS (Keduanya)",
    }
    return {
        "title": "💰 Ryukomik | Staff Pay Rates",
        "description": (
            "Rate berikut berlaku sebagai panduan bayaran per chapter. "
            "Nominal tugas tetap ditampilkan sebelum staff mulai mengerjakan."
        ),
        "color": 8162559,
        "fields": [
            {
                "name": labels[role],
                "value": (
                    f"**Rp{ranges[role][0]:,.0f} – Rp{ranges[role][1]:,.0f} / chapter**"
                    .replace(",", ".")
                ),
                "inline": False,
            }
            for role in ("TL", "TS", "TL+TS")
        ] + [{
            "name": "Ketentuan",
            "value": (
                "• Rate final ditentukan Administrator saat tugas dibuat.\n"
                "• Tugas multi-chapter dihitung: rate per chapter × jumlah chapter.\n"
                "• Perubahan rate resmi tidak mengubah tugas lama secara otomatis."
            ),
            "inline": False,
        }],
        "footer": {"text": "Ryukomik Official • Informasi rate staff terbaru"},
    }


async def update_discord_payrate_panel() -> bool:
    if DEV_BYPASS:
        return True
    ranges = {role: await role_rate_range(role) for role in DEFAULT_RATE_RANGES}
    messages = await discord_api(
        "GET", f"/channels/{STAFF_PAYRATE_CHANNEL_ID}/messages?limit=100"
    )
    embed = payrate_embed_payload(ranges)
    for message in messages or []:
        title = ((message.get("embeds") or [{}])[0].get("title") or "")
        if message.get("author", {}).get("bot") and "Staff Pay Rates" in title:
            return bool(await discord_api(
                "PATCH",
                f"/channels/{STAFF_PAYRATE_CHANNEL_ID}/messages/{message['id']}",
                {"embeds": [embed]},
            ))
    return bool(await discord_api(
        "POST",
        f"/channels/{STAFF_PAYRATE_CHANNEL_ID}/messages",
        {"embeds": [embed]},
    ))


async def broadcast_payrate_to_staff(role: str, min_rate: int, max_rate: int) -> int:
    """Broadcast only to members who currently hold the Staff role."""
    if DEV_BYPASS:
        return 0
    members = await discord_api("GET", f"/guilds/{GUILD_ID}/members?limit=1000") or []
    staff_ids = {
        int(member["user"]["id"])
        for member in members
        if ROLE_STAFF_ID in {int(value) for value in member.get("roles", [])}
    }
    channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels") or []
    ticket_map = {}
    for channel in channels:
        if channel.get("type") != 0 or "tiket-" not in channel.get("name", "").casefold():
            continue
        topic = channel.get("topic") or ""
        for staff_id in staff_ids:
            owns_overwrite = any(
                str(overwrite.get("id")) == str(staff_id)
                and overwrite.get("type") == 1
                for overwrite in channel.get("permission_overwrites", [])
            )
            if str(staff_id) in topic or owns_overwrite:
                ticket_map.setdefault(staff_id, channel["id"])
    labels = {"TL": "Translator (TL)", "TS": "Editor / Typesetter (TS)", "TL+TS": "TL + TS (Keduanya)"}
    sent = 0
    for staff_id, channel_id in ticket_map.items():
        message = {
            "embeds": [{
                "title": "📢 Payrate Staff Diperbarui",
                "description": (
                    f"Range **{labels[role]}** sekarang "
                    f"**Rp{min_rate:,.0f} – Rp{max_rate:,.0f} / chapter**."
                ).replace(",", "."),
                "color": 6253567,
                "footer": {"text": "Tugas lama tidak berubah • Berlaku untuk tugas berikutnya"},
            }],
        }
        if await discord_api("POST", f"/channels/{channel_id}/messages", message):
            sent += 1
    return sent


def recruitment_panel_payload(settings: dict[str, bool]) -> tuple[dict, list]:
    enabled = [position for position in ("TL", "TS", "TL+TS") if settings[position]]
    fields = []
    descriptions = {
        "TL": ("💬 TL — Translator", "Menerjemahkan dialog Bahasa Inggris ke Bahasa Indonesia secara natural."),
        "TS": ("🎨 TS — Typesetter / Editor", "Menangani cleaning, redrawing, dan typesetting chapter."),
        "TL+TS": ("✨ TL + TS — Keduanya", "Mengerjakan paket tes Translator dan Typesetter."),
    }
    for position in ("TL", "TS", "TL+TS"):
        name, value = descriptions[position]
        is_open = position in enabled
        fields.append({
            "name": name if is_open else f"{name} • CLOSED",
            "value": (
                value
                if is_open
                else f"{value}\n🔒 **Pendaftaran posisi ini sedang ditutup.**"
            ),
            "inline": False,
        })
    fields.append({
        "name": "📌 Persyaratan",
        "value": (
            "• Memiliki waktu luang dan bertanggung jawab.\n"
            "• Bisa berkomunikasi serta menerima revisi.\n"
            "• PC/laptop sangat disarankan untuk TS."
        ),
        "inline": False,
    })
    if enabled:
        fields.append({
            "name": "🔒 Tiket Privat",
            "value": "Tiket hanya dapat dilihat pelamar, administrator, dan bot.",
            "inline": False,
        })
    embed = {
        "title": "Ryukomik | Staff Recruitment",
        "description": (
            "Halo! Ryukomik sedang membuka kesempatan untuk bergabung sebagai staff scanlation."
            if enabled
            else "Rekrutmen staff sedang ditutup sementara. Silakan pantau panel ini untuk pembukaan berikutnya."
        ),
        "color": 5793266,
        "fields": fields,
        "footer": {"text": "Ryukomik Official • Recruitment System"},
    }
    components = [{
        "type": 1,
        "components": [{
            "type": 2,
            "style": 1,
            "label": "Buat Tiket Pendaftaran",
            "emoji": {"name": "📩"},
            "custom_id": "recruitment:create_ticket:v1",
            "disabled": not enabled,
        }],
    }]
    return embed, components


async def update_discord_recruitment_panel(settings: dict[str, bool]) -> bool:
    """Edit the existing recruitment panel without creating duplicates."""
    if DEV_BYPASS:
        return True
    channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels") or []
    candidates = [
        channel for channel in channels
        if channel.get("type") == 0
        and (
            "staff-rekrutmen" in channel.get("name", "").casefold()
            or "staff-recruitment" in channel.get("name", "").casefold()
        )
    ]
    embed, components = recruitment_panel_payload(settings)
    for channel in candidates:
        messages = await discord_api(
            "GET", f"/channels/{channel['id']}/messages?limit=100"
        ) or []
        for message in messages:
            title = ((message.get("embeds") or [{}])[0].get("title") or "")
            if message.get("author", {}).get("bot") and "Staff Recruitment" in title:
                updated = await discord_api(
                    "PATCH",
                    f"/channels/{channel['id']}/messages/{message['id']}",
                    {"embeds": [embed], "components": components},
                )
                return bool(updated)
    return False


def page_payload(items, page, page_size, total):
    return {
        "items": items, "page": page, "page_size": page_size, "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


def normalize_paging(page, page_size, paginated):
    return (
        page if isinstance(page, int) else 1,
        page_size if isinstance(page_size, int) else 20,
        paginated if isinstance(paginated, bool) else False,
    )


async def resolve_staff_ticket_channel(staff_id: int, assignment_id: int) -> str | None:
    """Find the private staff ticket from Discord, even for a first dashboard task."""
    connection = await dashboard_db()
    try:
        row = await (await connection.execute(
            "SELECT ticket_channel_id FROM assignments WHERE staff_id=? AND ticket_channel_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (staff_id,),
        )).fetchone()
    finally:
        await connection.close()
    channel_id = str(row[0]) if row and row[0] else None
    if not channel_id:
        channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels") or []
        for channel in channels:
            if channel.get("type") != 0 or "tiket-" not in str(channel.get("name", "")).casefold():
                continue
            topic = str(channel.get("topic") or "")
            owns_overwrite = any(
                str(overwrite.get("id")) == str(staff_id) and overwrite.get("type") == 1
                for overwrite in channel.get("permission_overwrites", [])
            )
            if str(staff_id) in topic or owns_overwrite:
                channel_id = str(channel["id"])
                break
    if channel_id:
        connection = await dashboard_db()
        try:
            await connection.execute("UPDATE assignments SET ticket_channel_id=? WHERE id=?", (channel_id, assignment_id))
            await connection.commit()
        finally:
            await connection.close()
    return channel_id


async def send_assignment_notice(staff_id: int, assignment_id: int, payload: AssignmentCreate, handoff_note: str | None = None):
    if DEV_BYPASS:
        return True
    channel_id = await resolve_staff_ticket_channel(staff_id, assignment_id)
    if not channel_id:
        dm = await discord_api("POST", "/users/@me/channels", {"recipient_id": str(staff_id)})
        channel_id = dm.get("id") if dm else None
    if not channel_id:
        return False
    message = {
        "content": f"<@{staff_id}> kamu mendapat tugas baru dari dashboard admin.",
        "embeds": [{
            "title": f"Tugas #{assignment_id} • {payload.manga}",
            "description": f"Chapter **{payload.chapter}** • Role **{payload.role}**",
            "color": 6253567,
            "fields": [
                {"name": "Bayaran", "value": f"Rp {payload.final_rate:,.0f}".replace(",", "."), "inline": True},
                {"name": "Deadline", "value": payload.deadline_at or "Tidak ditentukan", "inline": True},
            ] + ([{"name": "Bahan dari TL", "value": handoff_note, "inline": False}] if handoff_note else []),
            "footer": {"text": "Buka Staff Panel atau dashboard untuk melihat dan submit tugas."},
        }],
    }
    sent = bool(await discord_api("POST", f"/channels/{channel_id}/messages", message))
    if not sent:
        await operations.enqueue_notification(
            f"assignment:{assignment_id}:created", "assignment", channel_id,
            {"content": message["content"], "embed": message["embeds"][0]},
        )
    return sent


async def send_assignment_update_notice(before: dict, after: dict) -> bool:
    """Tell the assigned staff what changed, only in their private ticket."""
    if DEV_BYPASS or not after.get("staff_id") or not after.get("ticket_channel_id"):
        return bool(DEV_BYPASS)
    fields = []
    comparisons = (
        ("Manga", "manga"),
        ("Chapter", "chapter"),
        ("Role", "role"),
        ("Rate / Chapter", "rate_per_chapter"),
        ("Total Bayaran", "final_rate"),
        ("Deadline", "deadline_at"),
    )
    for label, key in comparisons:
        old_value, new_value = before.get(key), after.get(key)
        if old_value == new_value:
            continue
        if key in {"rate_per_chapter", "final_rate"}:
            old_value = f"Rp {int(old_value or 0):,.0f}".replace(",", ".")
            new_value = f"Rp {int(new_value or 0):,.0f}".replace(",", ".")
        fields.append({
            "name": label,
            "value": f"~~{old_value or 'Tidak ditentukan'}~~ → **{new_value or 'Tidak ditentukan'}**",
            "inline": False,
        })
    message = {
        "content": f"<@{after['staff_id']}>",
        "embeds": [{
            "title": f"📝 Tugas #{after['id']} Diperbarui",
            "description": "Administrator memperbarui detail tugas kamu.",
            "color": 16753920,
            "fields": fields,
            "footer": {"text": "Periksa detail terbaru sebelum melanjutkan pekerjaan."},
        }],
    }
    sent = bool(await discord_api(
        "POST",
        f"/channels/{after['ticket_channel_id']}/messages",
        message,
    ))
    if not sent:
        await operations.enqueue_notification(
            f"assignment:{after['id']}:updated:{hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:12]}",
            "assignment_updated",
            after["ticket_channel_id"],
            {"content": message["content"], "embed": message["embeds"][0]},
        )
    return sent


async def send_submission_notice(upload, username: str):
    if DEV_BYPASS:
        return True
    size_mb = upload["size_bytes"] / 1024 / 1024
    message = {
        "content": f"📥 <@{upload['staff_id']}> telah mengirim hasil tugas untuk direview.",
        "embeds": [{
            "title": f"Hasil Tugas #{upload['assignment_id']} Siap Direview",
            "description": f"**{upload['manga']}** · Chapter **{upload['chapter']}**",
            "color": 5763719,
            "fields": [
                {"name": "Staff", "value": username, "inline": True},
                {"name": "Role", "value": upload["role"], "inline": True},
                {"name": "File", "value": f"{upload['original_name']} ({size_mb:.1f} MB)", "inline": False},
            ],
            "footer": {"text": "Buka dashboard untuk download, lalu gunakan Review pada Admin Panel untuk Setuju/Revisi."},
        }],
        "components": [{
            "type": 1,
            "components": [{"type": 2, "style": 5, "label": "Buka Dashboard Review", "url": DASHBOARD_ORIGIN}],
        }],
    }
    return bool(await discord_api("POST", f"/channels/{STAFF_LOG_CHANNEL_ID}/messages", message))


async def send_ticket_review_notice(assignment: dict, approved: bool, notes: str | None = None):
    """Notify only the private staff ticket; never DM review results."""
    channel_id = assignment.get("ticket_channel_id")
    if DEV_BYPASS:
        return True
    if not channel_id:
        return False
    title = "✅ Tugas Selesai" if approved else "🔄 Tugas Perlu Revisi"
    description = (
        "Hasil kerja telah diperiksa dan **disetujui Administrator**. Bayaran sudah masuk ke rekap gaji."
        if approved
        else f"**{assignment['manga']}** chapter **{assignment['chapter']}** perlu diperbaiki sebelum dikirim ulang."
    )
    fields = [
        {"name": "Manga", "value": assignment["manga"], "inline": False},
        {"name": "Chapter", "value": assignment["chapter"], "inline": True},
        {"name": "Role", "value": assignment["role"], "inline": True},
    ]
    if approved:
        chapter_count = int(assignment.get("chapter_count") or 1)
        total = int(assignment.get("final_rate") or 0)
        rate = int(assignment.get("rate_per_chapter") or (total // chapter_count if chapter_count else total))
        fields.extend([
            {"name": "Jumlah Chapter", "value": str(chapter_count), "inline": True},
            {"name": "Rate per Chapter", "value": f"Rp {rate:,.0f}".replace(",", "."), "inline": True},
            {"name": "Total Bayaran", "value": f"Rp {total:,.0f}".replace(",", "."), "inline": True},
        ])
    if assignment.get("gdrive_link"):
        fields.append({
            "name": "Hasil Google Drive" if approved else "Hasil Sebelumnya",
            "value": assignment["gdrive_link"],
            "inline": False,
        })
    if notes:
        fields.append({"name": "Catatan Admin", "value": notes[:1024], "inline": False})
    message = {
        "content": f"<@{assignment['staff_id']}>",
        "embeds": [{
            "title": title,
            "description": description,
            "color": 5763719 if approved else 16753920,
            "fields": fields,
            "footer": {"text": f"Task #{assignment['id']} • {'Laporan akhir tugas' if approved else 'Perbaiki lalu submit kembali'}"},
        }],
    }
    sent = bool(await discord_api("POST", f"/channels/{channel_id}/messages", message))
    if not sent:
        event = "approved" if approved else "revision"
        await operations.enqueue_notification(
            f"assignment:{assignment['id']}:{event}", f"assignment_{event}", channel_id,
            {"content": message["content"], "embed": message["embeds"][0]},
        )
    return sent


async def send_payout_ticket_notice(staff_id: int, title: str, description: str, success: bool):
    connection = await dashboard_db()
    try:
        row = await (await connection.execute("""SELECT ticket_channel_id FROM assignments
            WHERE staff_id=? AND ticket_channel_id IS NOT NULL ORDER BY id DESC LIMIT 1""", (staff_id,))).fetchone()
    finally:
        await connection.close()
    if DEV_BYPASS:
        return True
    if not row:
        return False
    message = {
        "content": f"<@{staff_id}>",
        "embeds": [{"title": title, "description": description, "color": 5763719 if success else 15548997}],
    }
    sent = bool(await discord_api("POST", f"/channels/{row['ticket_channel_id']}/messages", message))
    if not sent:
        await operations.enqueue_notification(
            f"payout:{staff_id}:{hashlib.sha256((title+description).encode()).hexdigest()[:16]}",
            "payout_status", row["ticket_channel_id"],
            {"content": message["content"], "embed": message["embeds"][0]},
        )
    return sent


async def send_paid_invoice_pdf(payout_id: int, admin_name: str):
    detail = await payout_service.payout_detail(payout_id, include_sensitive=True)
    if not detail:
        return False, "Data invoice tidak ditemukan."
    if DEV_BYPASS:
        await payout_service.record_invoice_delivery(payout_id, message_id="dev")
        return True, None
    connection = await dashboard_db()
    try:
        row = await (await connection.execute("""SELECT ticket_channel_id FROM assignments
            WHERE staff_id=? AND ticket_channel_id IS NOT NULL ORDER BY id DESC LIMIT 1""",
            (detail["staff_id"],))).fetchone()
    finally:
        await connection.close()
    if not row:
        error = "Tiket privat staff tidak ditemukan."
        await payout_service.record_invoice_delivery(payout_id, error=error)
        return False, error
    profile = next((item for item in await staff_directory() if int(item["id"]) == int(detail["staff_id"])), None)
    try:
        pdf = render_paid_invoice(
            detail, staff_name=(profile or {}).get("username"), admin_name=admin_name
        )
        payload = {
            "content": f"<@{detail['staff_id']}>",
            "embeds": [{
                "title": "Invoice Gaji Lunas",
                "description": f"Pembayaran **Rp {detail['total_amount']:,.0f}** telah ditransfer.".replace(",", "."),
                "color": 5763719,
                "fields": [
                    {"name": "Invoice", "value": detail["invoice_number"], "inline": False},
                    {"name": "Periode", "value": detail["period"], "inline": True},
                    {"name": "Chapter", "value": str(detail["chapter_count"]), "inline": True},
                ],
            }],
            "attachments": [{"id": 0, "filename": f"{detail['invoice_number']}.pdf"}],
        }
        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps(payload))
        form.add_field(
            "files[0]", pdf, filename=f"{detail['invoice_number']}.pdf",
            content_type="application/pdf",
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://discord.com/api/v10/channels/{row['ticket_channel_id']}/messages",
                headers={"Authorization": f"Bot {TOKEN}"}, data=form,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                body = await response.json(content_type=None)
                if response.status >= 300:
                    raise RuntimeError(f"Discord HTTP {response.status}")
        await payout_service.record_invoice_delivery(payout_id, message_id=body.get("id"))
        return True, None
    except Exception as error:
        message = str(error)[:500]
        await payout_service.record_invoice_delivery(payout_id, error=message)
        await operations.record_event(
            "invoice", "error", "Dashboard gagal mengirim invoice PDF",
            {"payout_id": payout_id, "error": message},
        )
        return False, message


@app.get("/health")
async def health():
    database_status = "ok"
    try:
        connection = await dashboard_db()
        await connection.execute("SELECT 1")
        await connection.close()
    except Exception:
        database_status = "error"
    discord_status = "not_configured"
    if TOKEN:
        try:
            result = await discord_api("GET", "/users/@me")
            discord_status = "ok" if result and result.get("id") else "error"
        except Exception:
            discord_status = "error"
    try:
        payout_service._cipher()
        payment_encryption_status = "ok"
    except RuntimeError:
        payment_encryption_status = "not_configured"
    r2_status = "ok" if all((
        payout_service.R2_ENDPOINT, payout_service.R2_ACCESS_KEY_ID,
        payout_service.R2_SECRET_ACCESS_KEY, payout_service.R2_BUCKET_NAME,
    )) else "not_configured"
    operational = {"backup": "unknown", "outbox": "unknown"}
    try:
        snapshot = await operations.operations_snapshot()
        operational["backup"] = "ok" if snapshot["backups"] else "missing"
        operational["outbox"] = "degraded" if any(
            item["status"] == "failed" for item in snapshot["outbox"]
        ) else "ok"
    except Exception:
        pass
    return {
        "status": "ok" if database_status == "ok" and payment_encryption_status == "ok" else "degraded",
        "time": datetime.now().isoformat(),
        "components": {"database": database_status, "discord": discord_status,
                       "oauth": "ok" if DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET else "not_configured",
                       "payment_encryption": payment_encryption_status, "r2": r2_status,
                       **operational},
    }


@app.get("/auth/login")
async def login(request: Request):
    if DEV_BYPASS:
        return RedirectResponse(DASHBOARD_ORIGIN)
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET or not SESSION_SECRET:
        raise HTTPException(status_code=503, detail="Discord OAuth dashboard belum dikonfigurasi.")
    return await oauth.discord.authorize_redirect(request, f"{API_ORIGIN}/auth/callback")


@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.discord.authorize_access_token(request)
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        ) as response:
            profile = await response.json()
    member = await fetch_member(int(profile["id"]))
    role = role_from_member(member or {})
    if role != "admin":
        raise HTTPException(status_code=403, detail="Dashboard hanya tersedia untuk administrator Ryukomik.")
    request.session["user"] = {
        "id": int(profile["id"]),
        "username": profile.get("global_name") or profile["username"],
        "avatar": profile.get("avatar"),
        "role": role,
    }
    await cache_staff_profile({
        "id": int(profile["id"]),
        "username": profile.get("global_name") or profile["username"],
        "avatar": f"https://cdn.discordapp.com/avatars/{profile['id']}/{profile['avatar']}.png?size=128" if profile.get("avatar") else None,
    })
    return RedirectResponse(DASHBOARD_ORIGIN)


@app.post("/auth/logout")
async def logout(request: Request):
    expected = request.session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), expected):
        raise HTTPException(status_code=403, detail="Token keamanan tidak valid.")
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
async def me(request: Request, user=Depends(current_user)):
    return {**user, "id": str(user["id"]), "csrf_token": request.session["csrf_token"]}


@app.get("/api/overview")
async def overview(user=Depends(current_user)):
    connection = await dashboard_db()
    try:
        where, params = "", []
        if user["role"] == "staff":
            where, params = " WHERE staff_id = ?", [user["id"]]
        rows = await (await connection.execute(
            f"SELECT status, COUNT(*) count FROM assignments{where} GROUP BY status", params
        )).fetchall()
        counts = {row["status"]: row["count"] for row in rows}
        total = await (await connection.execute(
            f"SELECT COALESCE(SUM(final_rate),0) total FROM assignments{where}", params
        )).fetchone()
        due_where = "deadline_at IS NOT NULL AND status IN ('claimed','revision','submitted')"
        due_params = []
        if user["role"] == "staff":
            due_where += " AND staff_id = ?"
            due_params.append(user["id"])
        due = await (await connection.execute(
            f"SELECT COUNT(*) count FROM assignments WHERE {due_where} AND date(deadline_at) <= date('now','+2 day')",
            due_params,
        )).fetchone()
        project_where, project_params = "", []
        if user["role"] == "staff":
            project_where, project_params = " WHERE staff_id = ?", [user["id"]]
        projects = await (await connection.execute(
            f"""SELECT manga,
                       COALESCE(SUM(chapter_count), COUNT(*)) AS chapter_count,
                       SUM(CASE WHEN status IN ('claimed','revision') THEN chapter_count ELSE 0 END) AS active_chapters,
                       SUM(CASE WHEN status='submitted' THEN chapter_count ELSE 0 END) AS review_chapters,
                       SUM(CASE WHEN status='revision' THEN chapter_count ELSE 0 END) AS revision_chapters,
                       SUM(CASE WHEN status IN ('approved','paid') THEN chapter_count ELSE 0 END) AS completed_chapters,
                       MAX(assigned_at) AS last_activity
                FROM assignments{project_where}
                GROUP BY manga
                ORDER BY active_chapters DESC, review_chapters DESC, last_activity DESC
                LIMIT 8""",
            project_params,
        )).fetchall()
        return {
            "counts": counts,
            "total_value": total["total"],
            "urgent_deadlines": due["count"],
            "project_progress": [dict(row) for row in projects],
        }
    finally:
        await connection.close()


@app.get("/api/action-center")
async def action_center(_user=Depends(admin_user)):
    """One prioritized queue for everything that currently needs an admin action."""
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute("""
            SELECT id,'assignment' item_type,
                   CASE
                     WHEN status='submitted' THEN 'review'
                     WHEN deadline_at IS NOT NULL AND date(deadline_at)<date('now') THEN 'overdue'
                     ELSE 'deadline'
                   END action_type,
                   manga || ' • Ch. ' || chapter title,
                   staff_id, status, deadline_at due_at, submitted_at created_at,
                   CASE WHEN status='submitted' THEN 1
                        WHEN deadline_at IS NOT NULL AND date(deadline_at)<date('now') THEN 2
                        ELSE 3 END priority
            FROM assignments
            WHERE status='submitted'
               OR (status IN ('claimed','revision') AND deadline_at IS NOT NULL
                   AND date(deadline_at)<=date('now','+1 day'))
            ORDER BY priority,id DESC
        """)).fetchall()
        payouts = await (await connection.execute("""
            SELECT p.id,'payout' item_type,
                   CASE WHEN p.status='awaiting_method' THEN 'payment_method'
                        WHEN p.invoice_send_error IS NOT NULL THEN 'invoice_delivery'
                        ELSE 'transfer' END action_type,
                   i.invoice_number title,p.staff_id,p.status,NULL due_at,p.requested_at created_at,
                   CASE WHEN p.invoice_send_error IS NOT NULL THEN 1
                        WHEN p.status='issued' THEN 2 ELSE 3 END priority
            FROM payout_requests p JOIN dashboard_invoices i ON i.id=p.invoice_id
            WHERE p.status IN ('awaiting_method','issued')
               OR (p.status='paid' AND p.invoice_send_error IS NOT NULL)
            ORDER BY priority,p.id DESC
        """)).fetchall()
        return await enrich_staff([*rows, *payouts])
    finally:
        await connection.close()


async def _read_image_dimensions(session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore):
    """Read just enough bytes to identify dimensions; never download the RAW file."""
    if not url.startswith(("https://", "http://")):
        return None
    async with semaphore:
        try:
            async with session.get(
                url,
                headers={"Range": "bytes=0-524287"},
                allow_redirects=False,
            ) as response:
                if response.status not in {200, 206}:
                    return None
                payload = await response.content.read(524288)
            with Image.open(BytesIO(payload)) as image:
                return image.width, image.height
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, UnidentifiedImageError):
            return None


@app.post("/api/raw-rate-analysis")
async def raw_rate_analysis(payload: RawRateAnalysisRequest, _user=Depends(admin_user)):
    """Recommend a role rate from the matching RAW's pages and image heights."""
    try:
        requested_chapters = parse_chapters(payload.chapter)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    resolved = await resolve_assignment_raw(
        payload.manga.strip(),
        requested_chapters,
        {
            "asura": asura_downloader,
            "omega": omega_downloader,
            "doujiva": doujiva_downloader,
            "evascan": evascan_downloader,
            "thunder": thunder_downloader,
        },
        timeout=12,
    )
    if resolved.get("status") != "resolved":
        message = {
            "not_found": "Judul RAW tidak ditemukan di Asura, Omega, Doujiva, EvaScan, atau Thunder.",
            "ambiguous": "Judul RAW ambigu. Perjelas judul manga sebelum dianalisis.",
            "chapters_missing": "Chapter tugas belum tersedia pada sumber RAW yang ditemukan.",
            "timeout": "Analisis RAW terlalu lama. Coba lagi beberapa saat.",
        }.get(resolved.get("status"), "RAW tidak dapat dianalisis saat ini.")
        raise HTTPException(status_code=422, detail=message)

    source = resolved["source"]
    downloader = {"asura": asura_downloader, "omega": omega_downloader, "doujiva": doujiva_downloader, "evascan": evascan_downloader, "thunder": thunder_downloader}[source]
    image_sets = await asyncio.gather(
        *(downloader.get_chapter_images(resolved["manga"]["id"], chapter["id"])
          for chapter in resolved["chapters"]),
        return_exceptions=True,
    )
    image_urls = [url for item in image_sets if isinstance(item, list) for url in item]
    if not image_urls:
        raise HTTPException(status_code=422, detail="Daftar gambar RAW kosong. Coba lagi beberapa saat.")

    # A range request keeps this analysis light even for high-resolution RAW.
    semaphore = asyncio.Semaphore(8)
    timeout = aiohttp.ClientTimeout(total=18, connect=5, sock_read=8)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        dimensions = await asyncio.gather(
            *(_read_image_dimensions(session, url, semaphore) for url in image_urls),
            return_exceptions=True,
        )
    measured = [item for item in dimensions if isinstance(item, tuple)]
    workload = RawWorkload(
        page_count=len(image_urls),
        measured_pages=len(measured),
        total_height=sum(item[1] for item in measured),
        max_height=max((item[1] for item in measured), default=0),
        tall_pages=sum(item[1] > 8192 for item in measured),
    )
    label, level, reason = classify_workload(workload)
    minimum, maximum = await role_rate_range(payload.role)
    suggested = suggested_rate(minimum, maximum, workload)
    return {
        "source": source,
        "matched_title": resolved["manga"].get("title", payload.manga),
        "chapter_count": len(resolved["chapters"]),
        "page_count": workload.page_count,
        "measured_pages": workload.measured_pages,
        "max_height": workload.max_height,
        "total_height": workload.total_height,
        "tall_pages": workload.tall_pages,
        "workload": label,
        "reason": reason,
        "rate_per_chapter": suggested,
        "minimum_rate": minimum,
        "maximum_rate": maximum,
        "note": "Rekomendasi dapat diubah administrator sebelum tugas dikirim.",
    }


class PairRevisionRequest(BaseModel):
    target: Literal["tl", "ts", "both"]
    notes: str = Field(min_length=3, max_length=1500)


async def send_pair_ticket_notice(chapter: dict, staff_id: int, role: str, approved: bool, notes: str | None = None) -> bool:
    assignment_id = int(chapter["tl_assignment_id"] if role == "TL" else chapter["ts_assignment_id"])
    channel_id = await resolve_staff_ticket_channel(staff_id, assignment_id)
    if DEV_BYPASS:
        return True
    if not channel_id:
        return False
    rate = int(chapter["tl_rate_per_chapter"] if role == "TL" else chapter["ts_rate_per_chapter"])
    fields = [
        {"name": "Manga", "value": chapter["manga"], "inline": False},
        {"name": "Chapter", "value": chapter["chapter"], "inline": True},
        {"name": "Role", "value": role, "inline": True},
        {"name": "Ruang Proyek", "value": f"<#{chapter['channel_id']}>", "inline": False},
    ]
    if approved:
        fields.extend([
            {"name": "Bayaran", "value": f"Rp {rate:,.0f}".replace(",", "."), "inline": True},
            {"name": "Hasil Final", "value": chapter.get("final_link") or "Tidak tersedia", "inline": False},
        ])
    elif notes:
        fields.append({"name": "Catatan Revisi", "value": notes, "inline": False})
    return bool(await discord_api("POST", f"/channels/{channel_id}/messages", {
        "content": f"<@{staff_id}>",
        "embeds": [{
            "title": "✅ Chapter Pair Selesai" if approved else f"🔄 Perbaikan Pair untuk {role}",
            "description": (
                "Hasil final disetujui Administrator dan bayaran masuk ke saldo."
                if approved else "Administrator meminta perbaikan sebelum review final."
            ),
            "color": 5763719 if approved else 16753920,
            "fields": fields,
        }],
        "allowed_mentions": {"users": [str(staff_id)]},
    }))


@app.get("/api/deadlines")
async def deadlines(user=Depends(current_user)):
    clauses = ["deadline_at IS NOT NULL", "status IN ('claimed','revision','submitted')"]
    params = []
    if user["role"] == "staff":
        clauses.append("staff_id=?")
        params.append(user["id"])
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute(
            f"SELECT * FROM assignments WHERE {' AND '.join(clauses)} ORDER BY date(deadline_at) ASC LIMIT 100",
            params,
        )).fetchall()
        return await enrich_staff(rows)
    finally:
        await connection.close()


@app.get("/api/recap")
async def recap(period: str = Query(pattern=r"^\d{4}-\d{2}$"), _user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute("""
            SELECT staff_id, SUM(COALESCE(chapter_count,1)) chapter_count, SUM(final_rate) total_amount,
                   SUM(CASE WHEN status='approved' THEN final_rate ELSE 0 END) pending_amount,
                   SUM(CASE WHEN status='paid' THEN final_rate ELSE 0 END) paid_amount
            FROM assignments
            WHERE staff_id IS NOT NULL AND status IN ('approved','paid')
              AND (approved_at LIKE ? OR paid_period = ?)
            GROUP BY staff_id ORDER BY total_amount DESC
        """, (f"{period}%", period))).fetchall()
        return await enrich_staff(rows)
    finally:
        await connection.close()


@app.get("/api/recap-summary")
async def recap_summary(_user=Depends(admin_user)):
    """All-time salary totals; intentionally independent from the period filter."""
    connection = await dashboard_db()
    try:
        row = await (await connection.execute("""
            SELECT
                SUM(CASE WHEN status IN ('approved','paid') THEN final_rate ELSE 0 END) total_earned,
                SUM(CASE WHEN status='approved' THEN final_rate ELSE 0 END) unpaid_amount,
                SUM(CASE WHEN status='paid' THEN final_rate ELSE 0 END) paid_amount,
                SUM(CASE WHEN status IN ('approved','paid') THEN COALESCE(chapter_count,1) ELSE 0 END) chapter_count
            FROM assignments
            WHERE staff_id IS NOT NULL
        """)).fetchone()
        result = dict(row) if row else {}
        return {key: result.get(key) or 0 for key in (
            "total_earned", "unpaid_amount", "paid_amount", "chapter_count"
        )}
    finally:
        await connection.close()


async def _replace_invoice_items(connection, invoice, items, actor_id: int):
    if invoice["status"] != "issued":
        raise HTTPException(status_code=409, detail="Hanya invoice berstatus issued yang dapat direvisi.")
    bonus_total = int((await (await connection.execute(
        "SELECT COALESCE(SUM(amount),0) total FROM dashboard_invoice_bonus_items WHERE invoice_id=?",
        (invoice["id"],))).fetchone())["total"])
    if not items and not bonus_total:
        raise HTTPException(status_code=422, detail="Tidak ada tugas approved yang dapat dimasukkan ke invoice.")
    old_ids = [row["assignment_id"] for row in await (await connection.execute(
        "SELECT assignment_id FROM dashboard_invoice_items WHERE invoice_id=?", (invoice["id"],)
    )).fetchall()]
    await connection.execute("DELETE FROM dashboard_assignment_billing WHERE invoice_id=?", (invoice["id"],))
    await connection.execute("DELETE FROM dashboard_invoice_items WHERE invoice_id=?", (invoice["id"],))
    try:
        await connection.executemany("""INSERT INTO dashboard_invoice_items
            (invoice_id,assignment_id,manga,chapter,role,amount,assigned_at,approved_at,chapter_count,rate_per_chapter)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", [(invoice["id"], item["id"], item["manga"], item["chapter"], item["role"],
                                           item["final_rate"], item["assigned_at"], item["approved_at"],
                                           item["chapter_count"] or 1, item["rate_per_chapter"] or item["final_rate"]) for item in items])
        await connection.executemany("INSERT INTO dashboard_assignment_billing(assignment_id,invoice_id) VALUES(?,?)",
                                     [(item["id"], invoice["id"]) for item in items])
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Salah satu tugas sudah ditagihkan pada invoice lain.")
    await connection.execute("""UPDATE dashboard_invoices SET chapter_count=?,total_amount=?,
        revised_at=CURRENT_TIMESTAMP,revised_by=? WHERE id=?""",
        (sum(item["chapter_count"] or 1 for item in items), sum(item["final_rate"] for item in items) + bonus_total, actor_id, invoice["id"]))
    return old_ids


@app.post("/api/uploads/presign")
async def presign_upload(payload: UploadRequest, user=Depends(current_user)):
    raise HTTPException(status_code=410, detail="Upload baru melalui dashboard dinonaktifkan. Staff submit link Google Drive melalui Discord.")
    extension = os.path.splitext(payload.filename)[1].lower()
    if extension not in {".zip", ".7z", ".rar", ".psd", ".clip", ".txt", ".docx"}:
        raise HTTPException(status_code=422, detail="Gunakan ZIP, 7Z, RAR, PSD, CLIP, TXT, atau DOCX.")
    connection = await dashboard_db()
    try:
        assignment = await (await connection.execute(
            "SELECT * FROM assignments WHERE id=?", (payload.assignment_id,)
        )).fetchone()
        if not assignment:
            raise HTTPException(status_code=404, detail="Tugas tidak ditemukan.")
        if user["role"] != "admin" and assignment["staff_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Tugas ini bukan milik Anda.")
        if assignment["status"] not in ("claimed", "revision"):
            raise HTTPException(status_code=409, detail="Tugas ini tidak sedang dalam tahap pengerjaan/revisi.")
        filename = safe_object_part(os.path.splitext(payload.filename)[0]) + extension
        object_key = "/".join((
            "submissions", safe_object_part(assignment["manga"]),
            f"chapter-{safe_object_part(assignment['chapter'])}", assignment["role"].replace("+", "-"),
            f"task-{assignment['id']}", f"{assignment['staff_id']}-{int(datetime.now().timestamp())}-{secrets.token_hex(3)}-{filename}",
        ))
        cursor = await connection.execute("""
            INSERT INTO assignment_submissions
                (assignment_id,staff_id,object_key,original_name,content_type,size_bytes,status)
            VALUES(?,?,?,?,?,?,'pending')
        """, (assignment["id"], assignment["staff_id"], object_key, payload.filename, payload.content_type, payload.size_bytes))
        await connection.commit()
        upload_id = cursor.lastrowid
    finally:
        await connection.close()
    client = r2_client()
    upload_url = await asyncio.to_thread(client.generate_presigned_url, "put_object", Params={
        "Bucket": R2_BUCKET_NAME, "Key": object_key, "ContentType": payload.content_type,
    }, ExpiresIn=1800)
    return {"upload_id": upload_id, "upload_url": upload_url, "object_key": object_key, "expires_in": 1800}


@app.post("/api/uploads/{upload_id}/complete")
async def complete_upload(upload_id: int, user=Depends(current_user)):
    connection = await dashboard_db()
    try:
        upload = await (await connection.execute("""
            SELECT s.*, a.status assignment_status, a.manga, a.chapter, a.role FROM assignment_submissions s
            JOIN assignments a ON a.id=s.assignment_id WHERE s.id=?
        """, (upload_id,))).fetchone()
        if not upload:
            raise HTTPException(status_code=404, detail="Upload tidak ditemukan.")
        if user["role"] != "admin" and upload["staff_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Upload ini bukan milik Anda.")
        if upload["status"] == "uploaded":
            return {"ok": True, "assignment_id": upload["assignment_id"]}
        client = r2_client()
        try:
            metadata = await asyncio.to_thread(client.head_object, Bucket=R2_BUCKET_NAME, Key=upload["object_key"])
        except Exception:
            raise HTTPException(status_code=409, detail="File belum ditemukan di R2. Tunggu upload selesai lalu coba lagi.")
        if int(metadata.get("ContentLength", 0)) != upload["size_bytes"]:
            raise HTTPException(status_code=409, detail="Ukuran file di R2 tidak sesuai; upload ulang diperlukan.")
        await connection.execute(
            "UPDATE assignment_submissions SET status='uploaded', uploaded_at=CURRENT_TIMESTAMP WHERE id=?", (upload_id,)
        )
        await connection.execute("""
            UPDATE assignments SET status='submitted', submitted_at=CURRENT_TIMESTAMP,
                gdrive_link=? WHERE id=? AND status IN ('claimed','revision')
        """, (f"r2://{R2_BUCKET_NAME}/{upload['object_key']}", upload["assignment_id"]))
        await connection.commit()
    finally:
        await connection.close()
    await audit(user["id"], "submission.upload", "assignment", upload["assignment_id"], after={"upload_id": upload_id, "size": upload["size_bytes"]})
    notified = await send_submission_notice(upload, user.get("username") or f"Staff {upload['staff_id']}")
    return {"ok": True, "assignment_id": upload["assignment_id"], "notified": notified}


@app.get("/api/submissions")
async def submissions(assignment_id: int | None = None, user=Depends(current_user)):
    clauses, params = ["s.status='uploaded'"], []
    if assignment_id:
        clauses.append("s.assignment_id=?"); params.append(assignment_id)
    if user["role"] != "admin":
        clauses.append("s.staff_id=?"); params.append(user["id"])
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute(f"""
            SELECT s.*, a.manga, a.chapter, a.role FROM assignment_submissions s
            JOIN assignments a ON a.id=s.assignment_id
            WHERE {' AND '.join(clauses)} ORDER BY s.uploaded_at DESC LIMIT 200
        """, params)).fetchall()
        return [dict(row) for row in rows]
    finally:
        await connection.close()


@app.get("/api/submissions/{submission_id}/download")
async def submission_download(submission_id: int, user=Depends(current_user)):
    connection = await dashboard_db()
    try:
        row = await (await connection.execute(
            "SELECT * FROM assignment_submissions WHERE id=? AND status='uploaded'", (submission_id,)
        )).fetchone()
    finally:
        await connection.close()
    if not row:
        raise HTTPException(status_code=404, detail="Submission tidak ditemukan.")
    if user["role"] != "admin" and row["staff_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Submission ini bukan milik Anda.")
    client = r2_client()
    url = await asyncio.to_thread(client.generate_presigned_url, "get_object", Params={
        "Bucket": R2_BUCKET_NAME, "Key": row["object_key"], "ResponseContentDisposition": f'attachment; filename="{row["original_name"]}"',
    }, ExpiresIn=900)
    return {"download_url": url, "expires_in": 900}


async def send_bonus_ticket_notice(bonus: dict) -> bool:
    if DEV_BYPASS:
        return True
    connection = await dashboard_db()
    try:
        row = await (await connection.execute("""SELECT ticket_channel_id FROM assignments
            WHERE CAST(staff_id AS TEXT)=? AND ticket_channel_id IS NOT NULL
            ORDER BY id DESC LIMIT 1""", (str(bonus["staff_id"]),))).fetchone()
    finally:
        await connection.close()
    if not row or not row["ticket_channel_id"]:
        return False
    payload = {
        "content": f"<@{bonus['staff_id']}>",
        "allowed_mentions": {"users": [str(bonus["staff_id"])]},
        "embeds": [{
            "title": "Bonus Performa Disetujui",
            "description": "Terima kasih atas kontribusi dan konsistensi kamu bulan ini.",
            "color": 3196747,
            "fields": [
                {"name": "Periode", "value": bonus["period"], "inline": True},
                {"name": "Skor", "value": f"{bonus['total_score']:.1f}/100", "inline": True},
                {"name": "Pencapaian", "value": bonus.get("tier") or "-", "inline": True},
                {"name": "Bonus", "value": f"Rp {int(bonus['proposed_amount']):,.0f}".replace(",", "."), "inline": True},
                {"name": "Pembayaran", "value": "Masuk ke invoice gajian berikutnya.", "inline": False},
            ],
            "footer": {"text": "Rincian performa ini bersifat privat."},
        }],
    }
    return bool(await discord_api("POST", f"/channels/{row['ticket_channel_id']}/messages", payload))


@app.get("/api/audit")
async def audit_logs(
    _user=Depends(admin_user), page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100), paginated: bool = Query(default=False),
):
    page, page_size, paginated = normalize_paging(page, page_size, paginated)
    connection = await dashboard_db()
    try:
        if paginated:
            total = (await (await connection.execute(
                "SELECT COUNT(*) count FROM dashboard_audit_logs"
            )).fetchone())["count"]
            rows = await (await connection.execute(
                "SELECT * FROM dashboard_audit_logs ORDER BY id DESC LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            )).fetchall()
            return page_payload([dict(row) for row in rows], page, page_size, total)
        rows = await (await connection.execute(
            "SELECT * FROM dashboard_audit_logs ORDER BY id DESC LIMIT 100"
        )).fetchall()
        return [dict(row) for row in rows]
    finally:
        await connection.close()


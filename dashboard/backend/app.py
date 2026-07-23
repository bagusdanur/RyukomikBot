import json
import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
import secrets
import time
from collections import defaultdict, deque

import aiohttp
import aiosqlite
try:
    import boto3
except ImportError:  # Legacy R2 downloads are optional in local/test environments.
    boto3 = None
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from config import GUILD_ID, ROLE_ADMIN_ID, ROLE_STAFF_ID, STAFF_LOG_CHANNEL_ID, TOKEN
import database as staff_db
from database import DB_PATH, setup_database
from helpers.chapters import chapter_display, parse_chapters

ROLE_RATE_LIMITS = {"TL": 8000, "TS": 12000, "TL+TS": 15000}

load_dotenv()

DASHBOARD_ORIGIN = os.getenv("DASHBOARD_ORIGIN", "http://localhost:5173").rstrip("/")
API_ORIGIN = os.getenv("DASHBOARD_API_ORIGIN", "http://localhost:8000").rstrip("/")
SESSION_SECRET = os.getenv("DASHBOARD_SESSION_SECRET", "")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DEV_BYPASS = os.getenv("DASHBOARD_DEV_BYPASS", "false").lower() == "true"
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "ryukomik-staff-submissions")
R2_ENDPOINT = os.getenv("R2_ENDPOINT", f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else "")


async def dashboard_db():
    connection = await aiosqlite.connect(DB_PATH, timeout=30)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA busy_timeout=30000")
    await connection.execute("PRAGMA foreign_keys=ON")
    return connection


async def setup_dashboard_tables():
    connection = await dashboard_db()
    try:
        await connection.execute("PRAGMA foreign_keys=OFF")
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
        await connection.commit()
        await connection.execute("PRAGMA foreign_keys=ON")
    finally:
        await connection.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await setup_database()
    await setup_dashboard_tables()
    yield


app = FastAPI(title="Ryukomik Staff Dashboard API", version="0.1.0", lifespan=lifespan)
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

_rate_windows: dict[str, deque] = defaultdict(deque)
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if int(request.headers.get("content-length", "0") or 0) > 2 * 1024 * 1024:
        return JSONResponse({"detail": "Ukuran request melebihi batas 2 MB."}, status_code=413)
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
    base_rate: int = Field(ge=0, le=1_000_000)


class AssignmentCreate(BaseModel):
    manga: str = Field(min_length=2, max_length=150)
    chapter: str = Field(min_length=1, max_length=30)
    staff_id: int
    role: Literal["TL", "TS", "TL+TS"]
    rate_per_chapter: int | None = Field(default=None, ge=0, le=1_000_000)
    final_rate: int | None = Field(default=None, ge=0, le=1_000_000)
    deadline_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class InvoiceCreate(BaseModel):
    staff_id: int
    period: str = Field(pattern=r"^\d{4}-\d{2}$")


class RevisionRequest(BaseModel):
    notes: str = Field(min_length=3, max_length=1500)


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


def discord_avatar(member: dict) -> str | None:
    user = member.get("user", {})
    avatar = member.get("avatar") or user.get("avatar")
    if not avatar:
        return None
    if member.get("avatar"):
        return f"https://cdn.discordapp.com/guilds/{GUILD_ID}/users/{user['id']}/avatars/{avatar}.png?size=128"
    return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png?size=128"


def member_profile(member: dict):
    discord_user = member.get("user", {})
    if not discord_user.get("id"):
        return None
    return {"id": int(discord_user["id"]), "username": member.get("nick") or discord_user.get("global_name") or discord_user.get("username", "Staff"), "avatar": discord_avatar(member)}


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


async def staff_directory():
    if DEV_BYPASS:
        connection = await dashboard_db()
        try:
            rows = await (await connection.execute(
                "SELECT DISTINCT staff_id FROM assignments WHERE staff_id IS NOT NULL"
            )).fetchall()
            return [{"id": row[0], "username": f"Staff {row[0]}", "avatar": None} for row in rows]
        finally:
            await connection.close()
    connection = await dashboard_db()
    try:
        cached = await (await connection.execute("SELECT staff_id id, username, avatar FROM dashboard_staff_cache")).fetchall()
        known = await (await connection.execute("SELECT DISTINCT staff_id FROM assignments WHERE staff_id IS NOT NULL")).fetchall()
    finally:
        await connection.close()
    profiles = {row["id"]: dict(row) for row in cached}
    members = await discord_api("GET", f"/guilds/{GUILD_ID}/members?limit=1000") or []
    for member in members:
        roles = {int(role) for role in member.get("roles", [])}
        if ROLE_STAFF_ID not in roles and ROLE_ADMIN_ID not in roles:
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
    return sorted(profiles.values(), key=lambda item: item["username"].casefold())


async def enrich_staff(rows):
    profiles = {item["id"]: item for item in await staff_directory()}
    enriched = []
    for row in rows:
        item = dict(row)
        profile = profiles.get(item.get("staff_id"), {})
        item["staff_name"] = profile.get("username") or f"Staff {item.get('staff_id') or 'belum dipilih'}"
        item["staff_avatar"] = profile.get("avatar")
        if item.get("staff_id") is not None:
            item["staff_id"] = str(item["staff_id"])
        enriched.append(item)
    return enriched


async def send_assignment_notice(staff_id: int, assignment_id: int, payload: AssignmentCreate):
    if DEV_BYPASS:
        return True
    connection = await dashboard_db()
    try:
        row = await (await connection.execute(
            "SELECT ticket_channel_id FROM assignments WHERE staff_id=? AND ticket_channel_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (staff_id,),
        )).fetchone()
    finally:
        await connection.close()
    channel_id = row[0] if row else None
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
            ],
            "footer": {"text": "Buka Staff Panel atau dashboard untuk melihat dan submit tugas."},
        }],
    }
    return bool(await discord_api("POST", f"/channels/{channel_id}/messages", message))


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
    description = (f"**{assignment['manga']}** chapter **{assignment['chapter']}** " +
                   ("telah disetujui. Bayaran masuk rekap gaji." if approved else "perlu diperbaiki sebelum dikirim ulang."))
    fields = [{"name": "Status", "value": "Approved" if approved else "Revision", "inline": True}]
    if notes:
        fields.append({"name": "Catatan Admin", "value": notes[:1024], "inline": False})
    return bool(await discord_api("POST", f"/channels/{channel_id}/messages", {
        "content": f"<@{assignment['staff_id']}>",
        "embeds": [{"title": title, "description": description, "color": 5763719 if approved else 16753920, "fields": fields}],
    }))


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
    return {
        "status": "ok" if database_status == "ok" else "degraded",
        "time": datetime.now().isoformat(),
        "components": {"database": database_status, "discord": discord_status,
                       "oauth": "ok" if DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET else "not_configured"},
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
        return {"counts": counts, "total_value": total["total"], "urgent_deadlines": due["count"]}
    finally:
        await connection.close()


@app.get("/api/assignments")
async def assignments(
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    user=Depends(current_user),
):
    clauses, params = [], []
    if user["role"] == "staff":
        clauses.append("staff_id = ?")
        params.append(user["id"])
    if status:
        clauses.append("status = ?")
        params.append(status)
    if search:
        clauses.append("(manga LIKE ? OR chapter LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute(
            f"SELECT * FROM assignments{where} ORDER BY assigned_at DESC LIMIT 250", params
        )).fetchall()
        return await enrich_staff(rows)
    finally:
        await connection.close()


@app.post("/api/assignments", status_code=201)
async def create_dashboard_assignment(payload: AssignmentCreate, user=Depends(admin_user)):
    try:
        chapters = parse_chapters(payload.chapter)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    rate_per_chapter = payload.rate_per_chapter if payload.rate_per_chapter is not None else payload.final_rate
    if rate_per_chapter is None:
        raise HTTPException(status_code=422, detail="Bayaran per chapter wajib diisi.")
    if rate_per_chapter > ROLE_RATE_LIMITS[payload.role]:
        raise HTTPException(status_code=422, detail=f"Maksimum rate {payload.role} adalah {ROLE_RATE_LIMITS[payload.role]}.")
    profiles = {item["id"]: item for item in await staff_directory()}
    if payload.staff_id not in profiles:
        raise HTTPException(status_code=422, detail="Staff tidak ditemukan atau tidak memiliki role Staff.")
    assignment_id = await staff_db.create_assignment(
        manga=payload.manga.strip(), chapter=chapter_display(chapters), chapters=chapters, role=payload.role,
        base_rate=rate_per_chapter, rate_per_chapter=rate_per_chapter,
        final_rate=rate_per_chapter * len(chapters), multiplier=1.0,
        staff_id=payload.staff_id, deadline_at=payload.deadline_at,
    )
    notice_payload = payload.model_copy(update={
        "chapter": chapter_display(chapters),
        "rate_per_chapter": rate_per_chapter,
        "final_rate": rate_per_chapter * len(chapters),
    })
    notified = await send_assignment_notice(payload.staff_id, assignment_id, notice_payload)
    await audit(user["id"], "assignment.create", "assignment", assignment_id, after={
        **payload.model_dump(), "chapters": chapters, "chapter_count": len(chapters),
        "rate_per_chapter": rate_per_chapter, "final_rate": rate_per_chapter * len(chapters),
        "notified": notified,
    })
    return {"id": assignment_id, "notified": notified}


@app.post("/api/assignments/{assignment_id}/approve")
async def dashboard_approve_assignment(assignment_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        before = await (await connection.execute("SELECT * FROM assignments WHERE id=?", (assignment_id,))).fetchone()
    finally:
        await connection.close()
    if not before:
        raise HTTPException(status_code=404, detail="Tugas tidak ditemukan.")
    if before["status"] != "submitted":
        raise HTTPException(status_code=409, detail=f"Tugas berstatus {before['status']}, bukan submitted.")
    if not await staff_db.approve_assignment(assignment_id):
        raise HTTPException(status_code=409, detail="Status tugas berubah. Muat ulang dashboard.")
    after = await staff_db.get_assignment(assignment_id)
    notified = await send_ticket_review_notice(after, True)
    await audit(user["id"], "assignment.approve", "assignment", assignment_id, dict(before), {**after, "notified": notified})
    return {"ok": True, "notified": notified}


@app.post("/api/assignments/{assignment_id}/revision")
async def dashboard_revision_assignment(assignment_id: int, payload: RevisionRequest, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        before = await (await connection.execute("SELECT * FROM assignments WHERE id=?", (assignment_id,))).fetchone()
    finally:
        await connection.close()
    if not before:
        raise HTTPException(status_code=404, detail="Tugas tidak ditemukan.")
    if before["status"] != "submitted":
        raise HTTPException(status_code=409, detail=f"Tugas berstatus {before['status']}, bukan submitted.")
    if not await staff_db.revise_assignment(assignment_id, payload.notes.strip()):
        raise HTTPException(status_code=409, detail="Status tugas berubah. Muat ulang dashboard.")
    after = await staff_db.get_assignment(assignment_id)
    notified = await send_ticket_review_notice(after, False, payload.notes.strip())
    await audit(user["id"], "assignment.revision", "assignment", assignment_id, dict(before), {**after, "notified": notified})
    return {"ok": True, "notified": notified}


@app.get("/api/staff")
async def staff(_user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute("""
            SELECT staff_id,
                   COUNT(*) task_count,
                   SUM(CASE WHEN status IN ('claimed','submitted','revision') THEN 1 ELSE 0 END) active_count,
                   SUM(CASE WHEN status='approved' THEN final_rate ELSE 0 END) approved_amount,
                   SUM(CASE WHEN status='paid' THEN final_rate ELSE 0 END) paid_amount
            FROM assignments WHERE staff_id IS NOT NULL GROUP BY staff_id ORDER BY task_count DESC
        """)).fetchall()
        stats = {row["staff_id"]: dict(row) for row in rows}
    finally:
        await connection.close()
    directory = await staff_directory()
    result = []
    for profile in directory:
        staff_id = profile["id"]
        result.append({
            **profile,
            "id": str(staff_id),
            "staff_id": str(staff_id),
            **stats.get(staff_id, {"task_count": 0, "active_count": 0, "approved_amount": 0, "paid_amount": 0}),
        })
    return result


@app.get("/api/payrates")
async def payrates(_user=Depends(current_user)):
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute("SELECT * FROM payrates ORDER BY role")).fetchall()
        return [dict(row) for row in rows]
    finally:
        await connection.close()


@app.put("/api/payrates/{role}")
async def update_payrate(
    role: Literal["TL", "TS", "TL+TS"], payload: PayrateUpdate, user=Depends(admin_user)
):
    maximum = ROLE_RATE_LIMITS[role]
    if payload.base_rate > maximum:
        raise HTTPException(status_code=422, detail=f"Maksimum rate {role} adalah {maximum}.")
    connection = await dashboard_db()
    try:
        old = await (await connection.execute("SELECT * FROM payrates WHERE role=?", (role,))).fetchone()
        await connection.execute("""
            INSERT INTO payrates(role,base_rate,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(role) DO UPDATE SET base_rate=excluded.base_rate, updated_at=CURRENT_TIMESTAMP
        """, (role, payload.base_rate))
        await connection.commit()
    finally:
        await connection.close()
    await audit(user["id"], "payrate.update", "payrate", role, dict(old) if old else None, payload.model_dump())
    return {"role": role, "base_rate": payload.base_rate}


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


@app.get("/api/invoices")
async def invoices(period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"), _user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        where, params = (" WHERE period=?", [period]) if period else ("", [])
        rows = await (await connection.execute(
            f"SELECT * FROM dashboard_invoices{where} ORDER BY issued_at DESC LIMIT 200", params
        )).fetchall()
        return await enrich_staff(rows)
    finally:
        await connection.close()


@app.get("/api/invoices/{invoice_id}")
async def invoice_detail(invoice_id: int, _user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        invoice = await (await connection.execute(
            "SELECT * FROM dashboard_invoices WHERE id=?", (invoice_id,)
        )).fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")
        items = await (await connection.execute("""
            SELECT assignment_id,manga,chapter,role,amount,assigned_at,approved_at,
                   chapter_count,rate_per_chapter
            FROM dashboard_invoice_items WHERE invoice_id=? ORDER BY assignment_id
        """, (invoice_id,))).fetchall()
        if not items:
            status_clause = "paid_period=?" if invoice["status"] == "paid" else "status='approved' AND approved_at LIKE ?"
            items = await (await connection.execute(f"""
                SELECT id assignment_id,manga,chapter,role,final_rate amount,assigned_at,approved_at,
                       COALESCE(chapter_count,1) chapter_count,COALESCE(rate_per_chapter,final_rate) rate_per_chapter
                FROM assignments WHERE staff_id=? AND {status_clause} ORDER BY id
            """, (invoice["staff_id"], invoice["period"] if invoice["status"] == "paid" else f"{invoice['period']}%"))).fetchall()
        result = (await enrich_staff([invoice]))[0]
        result["items"] = [dict(item) for item in items]
        dates = [item["assigned_at"] for item in items if item["assigned_at"]]
        approved = [item["approved_at"] for item in items if item["approved_at"]]
        result["work_started_at"] = min(dates) if dates else None
        result["work_ended_at"] = max(approved) if approved else None
        return result
    finally:
        await connection.close()


@app.post("/api/invoices", status_code=201)
async def create_invoice(payload: InvoiceCreate, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        items = await (await connection.execute("""
            SELECT id,manga,chapter,role,final_rate,assigned_at,approved_at,
                   COALESCE(chapter_count,1) chapter_count,COALESCE(rate_per_chapter,final_rate) rate_per_chapter
            FROM assignments a WHERE staff_id=? AND status='approved' AND approved_at LIKE ?
              AND NOT EXISTS (SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id)
            ORDER BY id
        """, (payload.staff_id, f"{payload.period}%"))).fetchall()
        if not items:
            raise HTTPException(status_code=422, detail="Tidak ada tugas approved yang belum dibayar pada periode ini.")
        chapter_count = sum(item["chapter_count"] or 1 for item in items)
        total_amount = sum(item["final_rate"] for item in items)
        invoice_number = f"RYU-{payload.period.replace('-', '')}-{payload.staff_id}-{secrets.token_hex(2).upper()}"
        try:
            cursor = await connection.execute("""
                INSERT INTO dashboard_invoices
                    (invoice_number,staff_id,period,chapter_count,total_amount,status,issued_by)
                VALUES(?,?,?,?,?,'issued',?)
            """, (invoice_number, payload.staff_id, payload.period, chapter_count, total_amount, user["id"]))
            invoice_id = cursor.lastrowid
            await connection.executemany("""
                INSERT INTO dashboard_invoice_items
                    (invoice_id,assignment_id,manga,chapter,role,amount,assigned_at,approved_at,chapter_count,rate_per_chapter)
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, [(
                invoice_id, item["id"], item["manga"], item["chapter"], item["role"],
                item["final_rate"], item["assigned_at"], item["approved_at"],
                item["chapter_count"] or 1, item["rate_per_chapter"] or item["final_rate"]
            ) for item in items])
            await connection.executemany(
                "INSERT INTO dashboard_assignment_billing(assignment_id,invoice_id) VALUES(?,?)",
                [(item["id"], invoice_id) for item in items],
            )
            await connection.commit()
        except aiosqlite.IntegrityError:
            await connection.rollback()
            raise HTTPException(status_code=409, detail="Salah satu tugas sudah masuk invoice lain. Muat ulang data.")
    finally:
        await connection.close()
    await audit(user["id"], "invoice.create", "invoice", invoice_id, after={"invoice_number": invoice_number})
    return {"id": invoice_id, "invoice_number": invoice_number}


async def _replace_invoice_items(connection, invoice, items, actor_id: int):
    if invoice["status"] != "issued":
        raise HTTPException(status_code=409, detail="Hanya invoice berstatus issued yang dapat direvisi.")
    if not items:
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
        (sum(item["chapter_count"] or 1 for item in items), sum(item["final_rate"] for item in items), actor_id, invoice["id"]))
    return old_ids


@app.post("/api/invoices/{invoice_id}/refresh")
async def refresh_invoice(invoice_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        invoice = await (await connection.execute("SELECT * FROM dashboard_invoices WHERE id=?", (invoice_id,))).fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")
        items = await (await connection.execute("""
            SELECT a.id,a.manga,a.chapter,a.role,a.final_rate,a.assigned_at,a.approved_at,
                   COALESCE(a.chapter_count,1) chapter_count,COALESCE(a.rate_per_chapter,a.final_rate) rate_per_chapter
            FROM assignments a WHERE a.staff_id=? AND a.status='approved' AND a.approved_at LIKE ?
              AND (NOT EXISTS (SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id)
                   OR EXISTS (SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id AND b.invoice_id=?))
            ORDER BY a.id
        """, (invoice["staff_id"], f"{invoice['period']}%", invoice_id))).fetchall()
        before_items = await _replace_invoice_items(connection, invoice, items, user["id"])
        await connection.commit()
        after = {"chapter_count": sum(item["chapter_count"] or 1 for item in items), "total_amount": sum(item["final_rate"] for item in items),
                 "assignment_ids": [item["id"] for item in items]}
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()
    await audit(user["id"], "invoice.refresh", "invoice", invoice_id, {"assignment_ids": before_items}, after)
    return {"ok": True, **after}


@app.post("/api/invoices/{invoice_id}/correction", status_code=201)
async def create_correction_invoice(invoice_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        parent = await (await connection.execute("SELECT * FROM dashboard_invoices WHERE id=?", (invoice_id,))).fetchone()
        if not parent or parent["status"] != "paid":
            raise HTTPException(status_code=409, detail="Invoice koreksi hanya dapat dibuat dari invoice yang sudah lunas.")
        items = await (await connection.execute("""SELECT a.id,a.manga,a.chapter,a.role,a.final_rate,a.assigned_at,a.approved_at,
                   COALESCE(a.chapter_count,1) chapter_count,COALESCE(a.rate_per_chapter,a.final_rate) rate_per_chapter
            FROM assignments a WHERE a.staff_id=? AND a.status='approved' AND a.approved_at LIKE ?
              AND NOT EXISTS (SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id) ORDER BY a.id""",
            (parent["staff_id"], f"{parent['period']}%"))).fetchall()
        if not items:
            raise HTTPException(status_code=422, detail="Tidak ada tugas terlambat yang belum ditagihkan.")
        count = (await (await connection.execute("SELECT COUNT(*) n FROM dashboard_invoices WHERE parent_invoice_id=?", (invoice_id,))).fetchone())["n"] + 1
        number = f"{parent['invoice_number']}-C{count:02d}"
        cursor = await connection.execute("""INSERT INTO dashboard_invoices
            (invoice_number,staff_id,period,chapter_count,total_amount,status,issued_by,invoice_type,parent_invoice_id)
            VALUES(?,?,?,?,?,'issued',?,'correction',?)""",
            (number, parent["staff_id"], parent["period"], sum(i["chapter_count"] or 1 for i in items), sum(i["final_rate"] for i in items), user["id"], invoice_id))
        correction_id = cursor.lastrowid
        await connection.executemany("""INSERT INTO dashboard_invoice_items
            (invoice_id,assignment_id,manga,chapter,role,amount,assigned_at,approved_at,chapter_count,rate_per_chapter)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [(correction_id,i["id"],i["manga"],i["chapter"],i["role"],i["final_rate"],i["assigned_at"],i["approved_at"],
              i["chapter_count"] or 1,i["rate_per_chapter"] or i["final_rate"]) for i in items])
        await connection.executemany("INSERT INTO dashboard_assignment_billing(assignment_id,invoice_id) VALUES(?,?)",
                                     [(i["id"], correction_id) for i in items])
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()
    await audit(user["id"], "invoice.correction", "invoice", correction_id, after={"parent_invoice_id": invoice_id, "invoice_number": number})
    return {"id": correction_id, "invoice_number": number}


@app.post("/api/invoices/{invoice_id}/pay")
async def pay_invoice(invoice_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        invoice = await (await connection.execute(
            "SELECT * FROM dashboard_invoices WHERE id=?", (invoice_id,)
        )).fetchone()
        if not invoice or invoice["status"] != "issued":
            raise HTTPException(status_code=409, detail="Invoice tidak ditemukan atau sudah dibayar.")
        item_ids = [row["assignment_id"] for row in await (await connection.execute(
            "SELECT assignment_id FROM dashboard_invoice_items WHERE invoice_id=?", (invoice_id,)
        )).fetchall()]
        if item_ids:
            placeholders = ",".join("?" for _ in item_ids)
            await connection.execute(
                f"UPDATE assignments SET status='paid', paid_period=? WHERE status='approved' AND id IN ({placeholders})",
                [invoice["period"], *item_ids],
            )
        else:
            await connection.execute("""
                UPDATE assignments SET status='paid', paid_period=?
                WHERE staff_id=? AND status='approved' AND approved_at LIKE ?
            """, (invoice["period"], invoice["staff_id"], f"{invoice['period']}%"))
        await connection.execute(
            "UPDATE dashboard_invoices SET status='paid', paid_at=CURRENT_TIMESTAMP WHERE id=?",
            (invoice_id,),
        )
        await connection.execute("""
            INSERT INTO payments(staff_id,period,total_amount,chapter_count,status,paid_at)
            VALUES(?,?,?,?, 'paid', CURRENT_TIMESTAMP)
        """, (invoice["staff_id"], invoice["period"], invoice["total_amount"], invoice["chapter_count"]))
        await connection.commit()
    finally:
        await connection.close()
    await audit(user["id"], "invoice.pay", "invoice", invoice_id, before=dict(invoice), after={"status": "paid"})
    return {"ok": True}


@app.delete("/api/invoices/{invoice_id}")
async def delete_invoice(invoice_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        invoice = await (await connection.execute(
            "SELECT * FROM dashboard_invoices WHERE id=?", (invoice_id,)
        )).fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")
        if invoice["status"] == "paid":
            raise HTTPException(status_code=409, detail="Invoice yang sudah lunas tidak dapat dihapus.")
        if invoice["status"] == "void":
            raise HTTPException(status_code=409, detail="Invoice sudah dibatalkan.")
        await connection.execute("DELETE FROM dashboard_assignment_billing WHERE invoice_id=?", (invoice_id,))
        await connection.execute("UPDATE dashboard_invoices SET status='void',voided_at=CURRENT_TIMESTAMP,voided_by=? WHERE id=?", (user["id"], invoice_id))
        await connection.commit()
    finally:
        await connection.close()
    await audit(user["id"], "invoice.void", "invoice", invoice_id, before=dict(invoice), after={"status": "void"})
    return {"ok": True, "status": "void"}


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


@app.get("/api/audit")
async def audit_logs(_user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute(
            "SELECT * FROM dashboard_audit_logs ORDER BY id DESC LIMIT 100"
        )).fetchall()
        return [dict(row) for row in rows]
    finally:
        await connection.close()

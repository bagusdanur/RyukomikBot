import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

import aiohttp
import aiosqlite
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from config import GUILD_ID, ROLE_ADMIN_ID, ROLE_STAFF_ID, TOKEN
from database import DB_PATH, setup_database

ROLE_RATE_LIMITS = {"TL": 8000, "TS": 12000, "TL+TS": 15000}

load_dotenv()

DASHBOARD_ORIGIN = os.getenv("DASHBOARD_ORIGIN", "http://localhost:5173").rstrip("/")
API_ORIGIN = os.getenv("DASHBOARD_API_ORIGIN", "http://localhost:8000").rstrip("/")
SESSION_SECRET = os.getenv("DASHBOARD_SESSION_SECRET", "")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DEV_BYPASS = os.getenv("DASHBOARD_DEV_BYPASS", "false").lower() == "true"


async def dashboard_db():
    connection = await aiosqlite.connect(DB_PATH, timeout=30)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA busy_timeout=30000")
    await connection.execute("PRAGMA foreign_keys=ON")
    return connection


async def setup_dashboard_tables():
    connection = await dashboard_db()
    try:
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
        await connection.commit()
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
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)

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
        return {"id": 1, "username": "Development Admin", "avatar": None, "role": "admin"}
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Silakan masuk dengan Discord.")
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


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


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
    if not role:
        raise HTTPException(status_code=403, detail="Akun tidak memiliki role Admin atau Staff Ryukomik.")
    request.session["user"] = {
        "id": int(profile["id"]),
        "username": profile.get("global_name") or profile["username"],
        "avatar": profile.get("avatar"),
        "role": role,
    }
    return RedirectResponse(DASHBOARD_ORIGIN)


@app.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
async def me(user=Depends(current_user)):
    return user


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
        return [dict(row) for row in rows]
    finally:
        await connection.close()


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
        return [dict(row) for row in rows]
    finally:
        await connection.close()


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
        return [dict(row) for row in rows]
    finally:
        await connection.close()


@app.get("/api/recap")
async def recap(period: str = Query(pattern=r"^\d{4}-\d{2}$"), _user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute("""
            SELECT staff_id, COUNT(*) chapter_count, SUM(final_rate) total_amount
            FROM assignments
            WHERE status='approved' AND approved_at LIKE ?
            GROUP BY staff_id ORDER BY total_amount DESC
        """, (f"{period}%",))).fetchall()
        return [dict(row) for row in rows]
    finally:
        await connection.close()


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

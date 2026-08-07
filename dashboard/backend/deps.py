"""Shared dependencies for dashboard backend — extracted from app.py."""

import json
import os
import asyncio
import secrets
from collections import defaultdict, deque

import aiosqlite
from dotenv import load_dotenv
from fastapi import HTTPException, Request
from fastapi import Depends
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from config import ROLE_ADMIN_ID, ROLE_STAFF_ID
from database import DB_PATH

load_dotenv()

# --- Config ---
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
TRAKTEER_WEBHOOK_TOKEN = os.getenv("TRAKTEER_WEBHOOK_TOKEN", "")
TRAKTEER_TIP_URL = os.getenv("TRAKTEER_TIP_URL", "https://trakteer.id/kanimenia17/tip")
TRAKTEER_CHANNEL_NAME = "apresiasi-staff"

# --- Staff cache ---
_staff_cache: dict = {"items": [], "expires_at": 0.0, "updated_at": None}
_staff_cache_lock = asyncio.Lock()

# --- Rate limiting ---
_rate_windows: dict[str, deque] = defaultdict(deque)
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# --- Pydantic models ---
class PayrateUpdate(BaseModel):
    min_rate: int | None = Field(default=None, ge=0, le=1_000_000)
    max_rate: int | None = Field(default=None, ge=0, le=1_000_000)
    base_rate: int | None = Field(default=None, ge=0, le=1_000_000)


# --- DB helper with connection pool ---
import asyncio as _asyncio
from contextlib import asynccontextmanager

_pool: list = []
_pool_lock = _asyncio.Lock()
_MAX_POOL_SIZE = 5


class _PooledConnection:
    """Wrapper that returns connection to pool on close()."""
    def __init__(self, conn):
        object.__setattr__(self, '_conn', conn)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)

    async def close(self):
        """Return to pool instead of closing."""
        async with _pool_lock:
            if len(_pool) < _MAX_POOL_SIZE:
                _pool.append(self._conn)
            else:
                await self._conn.close()

    async def commit(self):
        return await self._conn.commit()

    async def execute(self, *a, **kw):
        return await self._conn.execute(*a, **kw)

    async def executescript(self, *a, **kw):
        return await self._conn.executescript(*a, **kw)


async def dashboard_db():
    """Get a DB connection from pool or create new one."""
    async with _pool_lock:
        if _pool:
            conn = _pool.pop()
            try:
                await conn.execute("SELECT 1")
                return _PooledConnection(conn)
            except Exception:
                pass
    connection = await aiosqlite.connect(DB_PATH, timeout=30)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA busy_timeout=30000")
    await connection.execute("PRAGMA foreign_keys=ON")
    return _PooledConnection(connection)


# --- Auth dependencies ---
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


# --- Audit logging ---
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


# --- Helpers ---
DEFAULT_RATE_RANGES = {
    "TL": (4000, 8000),
    "TS": (5000, 10000),
    "TL+TS": (9000, 18000),
}


def normalize_paging(page: int, page_size: int, paginated: bool):
    if not paginated:
        return page, page_size, False
    return max(1, page), min(100, max(1, page_size)), True


def page_payload(items: list, page: int, page_size: int, total: int):
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, -(-total // page_size)),
    }

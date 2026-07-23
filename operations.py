"""Operational monitoring, durable notification outbox, and verified backups."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite

from database import DB_PATH

JAKARTA = ZoneInfo("Asia/Jakarta")
BACKUP_DIR = Path(DB_PATH).parent / "backups"
R2_BACKUP_PREFIX = "database-backups"


async def _db():
    connection = await aiosqlite.connect(DB_PATH, timeout=30)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA busy_timeout=30000")
    return connection


async def setup_operations():
    connection = await _db()
    try:
        await connection.executescript("""
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                component TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                context_json TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME,
                resolved_by TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_system_events_status
                ON system_events(status,severity,last_seen_at);
            CREATE TABLE IF NOT EXISTS notification_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deduplication_key TEXT NOT NULL UNIQUE,
                notification_type TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                locked_at DATETIME,
                sent_at DATETIME,
                last_error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_due
                ON notification_outbox(status,next_attempt_at);
            CREATE TABLE IF NOT EXISTS scheduler_runs (
                job_name TEXT PRIMARY KEY,
                last_started_at DATETIME,
                last_succeeded_at DATETIME,
                last_failed_at DATETIME,
                last_error TEXT,
                duration_ms INTEGER
            );
            CREATE TABLE IF NOT EXISTS backup_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                local_path TEXT NOT NULL,
                r2_object_key TEXT,
                size_bytes INTEGER,
                sha256 TEXT,
                integrity_status TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await connection.commit()
    finally:
        await connection.close()


def _fingerprint(component, message, context):
    stable = json.dumps(context or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{component}|{message}|{stable}".encode()).hexdigest()


async def record_event(component, severity, message, context=None):
    safe_message = str(message)[:1000]
    safe_context = json.dumps(context or {}, ensure_ascii=False)[:4000]
    fingerprint = _fingerprint(component, safe_message, context)
    connection = await _db()
    try:
        await connection.execute("""
            INSERT INTO system_events
                (fingerprint,component,severity,message,context_json)
            VALUES (?,?,?,?,?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                occurrence_count=occurrence_count+1,
                severity=excluded.severity,
                context_json=excluded.context_json,
                status='active',last_seen_at=CURRENT_TIMESTAMP,
                resolved_at=NULL,resolved_by=NULL
        """, (fingerprint, component, severity, safe_message, safe_context))
        await connection.commit()
    finally:
        await connection.close()


async def resolve_event(event_id, actor_id):
    connection = await _db()
    try:
        cursor = await connection.execute("""
            UPDATE system_events SET status='resolved',resolved_at=CURRENT_TIMESTAMP,
                resolved_by=? WHERE id=? AND status='active'
        """, (str(actor_id), event_id))
        await connection.commit()
        return cursor.rowcount > 0
    finally:
        await connection.close()


async def enqueue_notification(key, notification_type, channel_id, payload):
    connection = await _db()
    try:
        cursor = await connection.execute("""
            INSERT OR IGNORE INTO notification_outbox
                (deduplication_key,notification_type,channel_id,payload_json)
            VALUES (?,?,?,?)
        """, (key, notification_type, str(channel_id), json.dumps(payload, ensure_ascii=False)))
        await connection.commit()
        return cursor.rowcount > 0
    finally:
        await connection.close()


async def recover_outbox():
    connection = await _db()
    try:
        await connection.execute("""
            UPDATE notification_outbox SET status='retry',locked_at=NULL,
                next_attempt_at=CURRENT_TIMESTAMP
            WHERE status='processing'
              AND datetime(locked_at)<=datetime('now','-10 minutes')
        """)
        await connection.commit()
    finally:
        await connection.close()


async def due_notifications(limit=25):
    connection = await _db()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        rows = await (await connection.execute("""
            SELECT * FROM notification_outbox
            WHERE status IN ('pending','retry')
              AND datetime(next_attempt_at)<=datetime('now')
            ORDER BY id LIMIT ?
        """, (limit,))).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            await connection.execute(
                f"UPDATE notification_outbox SET status='processing',locked_at=CURRENT_TIMESTAMP "
                f"WHERE id IN ({placeholders})", ids,
            )
        await connection.commit()
        return [dict(row) for row in rows]
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()


async def finish_notification(item_id, error=None, permanent=False):
    connection = await _db()
    try:
        if not error:
            await connection.execute("""
                UPDATE notification_outbox SET status='sent',sent_at=CURRENT_TIMESTAMP,
                    locked_at=NULL,last_error=NULL WHERE id=?
            """, (item_id,))
        else:
            row = await (await connection.execute(
                "SELECT attempt_count FROM notification_outbox WHERE id=?", (item_id,)
            )).fetchone()
            attempts = int(row["attempt_count"] if row else 0) + 1
            delays = (10, 30, 120, 600, 1800)
            failed = permanent or attempts >= len(delays)
            delay = delays[min(attempts - 1, len(delays) - 1)]
            await connection.execute("""
                UPDATE notification_outbox SET status=?,attempt_count=?,
                    next_attempt_at=datetime('now',?),locked_at=NULL,last_error=?
                WHERE id=?
            """, (
                "failed" if failed else "retry", attempts, f"+{delay} seconds",
                str(error)[:1000], item_id,
            ))
        await connection.commit()
    finally:
        await connection.close()


async def retry_notification(item_id):
    connection = await _db()
    try:
        cursor = await connection.execute("""
            UPDATE notification_outbox SET status='retry',next_attempt_at=CURRENT_TIMESTAMP,
                locked_at=NULL,last_error=NULL WHERE id=? AND status='failed'
        """, (item_id,))
        await connection.commit()
        return cursor.rowcount > 0
    finally:
        await connection.close()


async def mark_scheduler(job_name, started_at, error=None):
    elapsed = int((datetime.now(JAKARTA) - started_at).total_seconds() * 1000)
    connection = await _db()
    try:
        await connection.execute("""
            INSERT INTO scheduler_runs
                (job_name,last_started_at,last_succeeded_at,last_failed_at,last_error,duration_ms)
            VALUES (?,CURRENT_TIMESTAMP,
                    CASE WHEN ? IS NULL THEN CURRENT_TIMESTAMP END,
                    CASE WHEN ? IS NOT NULL THEN CURRENT_TIMESTAMP END,?,?)
            ON CONFLICT(job_name) DO UPDATE SET
                last_started_at=CURRENT_TIMESTAMP,
                last_succeeded_at=CASE WHEN excluded.last_error IS NULL
                    THEN CURRENT_TIMESTAMP ELSE scheduler_runs.last_succeeded_at END,
                last_failed_at=CASE WHEN excluded.last_error IS NOT NULL
                    THEN CURRENT_TIMESTAMP ELSE scheduler_runs.last_failed_at END,
                last_error=excluded.last_error,duration_ms=excluded.duration_ms
        """, (job_name, error, error, str(error)[:1000] if error else None, elapsed))
        await connection.commit()
    finally:
        await connection.close()


async def daily_job_due(job_name, today=None):
    today = today or datetime.now(JAKARTA).date().isoformat()
    connection = await _db()
    try:
        row = await (await connection.execute(
            "SELECT date(last_succeeded_at,'+7 hours') succeeded FROM scheduler_runs WHERE job_name=?",
            (job_name,),
        )).fetchone()
        return not row or row["succeeded"] != today
    finally:
        await connection.close()


def _backup_sync(source, destination):
    source_connection = sqlite3.connect(source)
    backup_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(backup_connection)
        integrity = backup_connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        backup_connection.close()
        source_connection.close()
    return integrity


async def create_verified_backup(r2_client=None, bucket=None):
    await setup_operations()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(JAKARTA)
    base = f"ryukomik-{now:%Y%m%d-%H%M%S}.db"
    raw_path = BACKUP_DIR / base
    gz_path = BACKUP_DIR / f"{base}.gz"
    try:
        integrity = await asyncio.to_thread(_backup_sync, DB_PATH, raw_path)
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check: {integrity}")
        with raw_path.open("rb") as source, gzip.open(gz_path, "wb", compresslevel=6) as target:
            shutil.copyfileobj(source, target)
        raw_path.unlink(missing_ok=True)
        digest = hashlib.sha256(gz_path.read_bytes()).hexdigest()
        object_key = f"{R2_BACKUP_PREFIX}/{now:%Y/%m}/{gz_path.name}"
        if r2_client and bucket:
            await asyncio.to_thread(
                r2_client.upload_file, str(gz_path), bucket, object_key,
                ExtraArgs={"ContentType": "application/gzip"},
            )
        connection = await _db()
        try:
            await connection.execute("""
                INSERT INTO backup_records
                    (filename,local_path,r2_object_key,size_bytes,sha256,integrity_status,status)
                VALUES (?,?,?,?,?,?,'success')
            """, (
                gz_path.name, str(gz_path), object_key if r2_client else None,
                gz_path.stat().st_size, digest, integrity,
            ))
            await connection.commit()
        finally:
            await connection.close()
        await cleanup_backups(now)
        return {"path": str(gz_path), "sha256": digest, "r2_object_key": object_key}
    except Exception as error:
        await record_event("backup", "critical", "Backup database gagal", {"error": str(error)[:500]})
        raise


async def cleanup_backups(now=None):
    now = now or datetime.now(JAKARTA)
    cutoff = now - timedelta(days=30)
    for path in BACKUP_DIR.glob("ryukomik-*.db.gz"):
        modified = datetime.fromtimestamp(path.stat().st_mtime, JAKARTA)
        if modified < cutoff:
            path.unlink(missing_ok=True)


async def operations_snapshot():
    connection = await _db()
    try:
        events = await (await connection.execute("""
            SELECT * FROM system_events WHERE status='active'
            ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'error' THEN 2
                     WHEN 'warning' THEN 3 ELSE 4 END,last_seen_at DESC LIMIT 100
        """)).fetchall()
        outbox = await (await connection.execute("""
            SELECT * FROM notification_outbox
            WHERE status IN ('pending','retry','failed','processing')
            ORDER BY id DESC LIMIT 100
        """)).fetchall()
        schedulers = await (await connection.execute(
            "SELECT * FROM scheduler_runs ORDER BY job_name"
        )).fetchall()
        backups = await (await connection.execute(
            "SELECT * FROM backup_records ORDER BY id DESC LIMIT 20"
        )).fetchall()
        return {
            "events": [dict(row) for row in events],
            "outbox": [dict(row) for row in outbox],
            "schedulers": [dict(row) for row in schedulers],
            "backups": [dict(row) for row in backups],
        }
    finally:
        await connection.close()

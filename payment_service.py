"""Shared salary payout service used by Discord and the admin dashboard."""

import asyncio
import json
import os
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import aiosqlite
try:
    import boto3
except ImportError:
    boto3 = None
from cryptography.fernet import Fernet, InvalidToken

from database import DB_PATH

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ENDPOINT = os.getenv("R2_ENDPOINT", f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "ryukomik-staff-submissions")
PAYMENT_DATA_ENCRYPTION_KEY = os.getenv("PAYMENT_DATA_ENCRYPTION_KEY", "")


def _cipher():
    if not PAYMENT_DATA_ENCRYPTION_KEY:
        raise RuntimeError("PAYMENT_DATA_ENCRYPTION_KEY belum dikonfigurasi.")
    try:
        return Fernet(PAYMENT_DATA_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as error:
        raise RuntimeError("PAYMENT_DATA_ENCRYPTION_KEY tidak valid.") from error


def encrypt_value(value):
    return _cipher().encrypt(str(value).encode()).decode()


def decrypt_value(value):
    try:
        return _cipher().decrypt(str(value).encode()).decode()
    except InvalidToken as error:
        raise RuntimeError("Data pembayaran tidak dapat didekripsi.") from error


def mask_account(value):
    value = str(value or "")
    return f"****{value[-4:]}" if value else "-"


def r2_client():
    if boto3 is None or not all((R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME)):
        raise RuntimeError("Konfigurasi Cloudflare R2 belum lengkap.")
    return boto3.client(
        "s3", endpoint_url=R2_ENDPOINT, aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY, region_name="auto",
    )


async def _db():
    connection = await aiosqlite.connect(DB_PATH, timeout=30)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA busy_timeout=30000")
    await connection.execute("PRAGMA foreign_keys=ON")
    return connection


async def setup_payment_tables():
    connection = await _db()
    try:
        await connection.executescript("""
            CREATE TABLE IF NOT EXISTS dashboard_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT NOT NULL UNIQUE, staff_id INTEGER NOT NULL,
                period TEXT NOT NULL, chapter_count INTEGER NOT NULL, total_amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'issued', issued_by INTEGER NOT NULL,
                issued_at DATETIME DEFAULT CURRENT_TIMESTAMP, paid_at DATETIME,
                invoice_type TEXT NOT NULL DEFAULT 'standard', parent_invoice_id INTEGER,
                revised_at DATETIME, revised_by INTEGER, voided_at DATETIME, voided_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS dashboard_invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL,
                assignment_id INTEGER NOT NULL, manga TEXT NOT NULL, chapter TEXT NOT NULL,
                role TEXT NOT NULL, amount INTEGER NOT NULL, assigned_at DATETIME, approved_at DATETIME,
                chapter_count INTEGER NOT NULL DEFAULT 1, rate_per_chapter INTEGER,
                UNIQUE(invoice_id,assignment_id)
            );
            CREATE TABLE IF NOT EXISTS dashboard_assignment_billing (
                assignment_id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS staff_payment_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                method_type TEXT NOT NULL CHECK(method_type IN ('bank','ewallet','qris')),
                provider TEXT NOT NULL,
                account_name TEXT NOT NULL,
                account_encrypted TEXT,
                account_last4 TEXT,
                qris_object_key TEXT,
                is_default INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_payment_methods_staff
                ON staff_payment_methods(staff_id,is_active);
            CREATE TABLE IF NOT EXISTS payout_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                payout_type TEXT NOT NULL CHECK(payout_type IN ('scheduled','instant')),
                cycle_key TEXT,
                cutoff_start TEXT,
                cutoff_end TEXT,
                invoice_id INTEGER NOT NULL,
                payment_method_id INTEGER,
                method_snapshot_encrypted TEXT NOT NULL,
                chapter_count INTEGER NOT NULL,
                total_amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'issued',
                requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                processed_at DATETIME,
                processed_by INTEGER,
                rejection_reason TEXT,
                UNIQUE(cycle_key,staff_id)
            );
            CREATE INDEX IF NOT EXISTS idx_payout_staff_status
                ON payout_requests(staff_id,status);
            CREATE TABLE IF NOT EXISTS payout_cycle_events (
                cycle_key TEXT NOT NULL, staff_id INTEGER NOT NULL,
                event_type TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(cycle_key,staff_id,event_type)
            );
        """)
        payout_columns = {
            row["name"] for row in await (
                await connection.execute("PRAGMA table_info(payout_requests)")
            ).fetchall()
        }
        for name, definition in (
            ("invoice_sent_at", "DATETIME"),
            ("invoice_message_id", "TEXT"),
            ("invoice_send_attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("invoice_send_error", "TEXT"),
        ):
            if name not in payout_columns:
                await connection.execute(f"ALTER TABLE payout_requests ADD COLUMN {name} {definition}")
        await connection.commit()
    finally:
        await connection.close()


async def create_method(staff_id, method_type, provider, account_name, account_number=None, qris_object_key=None):
    if method_type not in {"bank", "ewallet", "qris"}:
        raise ValueError("Jenis metode pembayaran tidak valid.")
    if method_type == "qris" and not qris_object_key:
        raise ValueError("Gambar QRIS wajib tersedia.")
    if method_type != "qris" and not account_number:
        raise ValueError("Nomor rekening atau e-wallet wajib diisi.")
    encrypted = encrypt_value(account_number) if account_number else None
    last4 = str(account_number)[-4:] if account_number else None
    connection = await _db()
    try:
        has_default = await (await connection.execute(
            "SELECT 1 FROM staff_payment_methods WHERE staff_id=? AND is_active=1 AND is_default=1", (staff_id,)
        )).fetchone()
        cursor = await connection.execute("""INSERT INTO staff_payment_methods
            (staff_id,method_type,provider,account_name,account_encrypted,account_last4,qris_object_key,is_default)
            VALUES(?,?,?,?,?,?,?,?)""",
            (staff_id, method_type, provider.strip(), account_name.strip(), encrypted, last4, qris_object_key, 0 if has_default else 1))
        await connection.commit()
        method_id = cursor.lastrowid
    finally:
        await connection.close()
    await attach_payment_method_to_waiting(staff_id, method_id if not has_default else None)
    return method_id


async def list_methods(staff_id, include_sensitive=False):
    connection = await _db()
    try:
        rows = await (await connection.execute("""SELECT * FROM staff_payment_methods
            WHERE staff_id=? AND is_active=1 ORDER BY is_default DESC,id""", (staff_id,))).fetchall()
    finally:
        await connection.close()
    result = []
    for row in rows:
        item = dict(row)
        item["masked_account"] = mask_account(item["account_last4"])
        if include_sensitive and item["account_encrypted"]:
            item["account_number"] = decrypt_value(item["account_encrypted"])
        item.pop("account_encrypted", None)
        result.append(item)
    return result


async def set_default_method(staff_id, method_id):
    connection = await _db()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        row = await (await connection.execute(
            "SELECT id FROM staff_payment_methods WHERE id=? AND staff_id=? AND is_active=1", (method_id, staff_id)
        )).fetchone()
        if not row:
            raise ValueError("Metode pembayaran tidak ditemukan.")
        await connection.execute("UPDATE staff_payment_methods SET is_default=0 WHERE staff_id=?", (staff_id,))
        await connection.execute("UPDATE staff_payment_methods SET is_default=1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (method_id,))
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()


async def deactivate_method(staff_id, method_id):
    connection = await _db()
    object_key = None
    try:
        await connection.execute("BEGIN IMMEDIATE")
        row = await (await connection.execute(
            "SELECT * FROM staff_payment_methods WHERE id=? AND staff_id=? AND is_active=1", (method_id, staff_id)
        )).fetchone()
        if not row:
            raise ValueError("Metode pembayaran tidak ditemukan.")
        object_key = row["qris_object_key"]
        await connection.execute("UPDATE staff_payment_methods SET is_active=0,is_default=0,updated_at=CURRENT_TIMESTAMP WHERE id=?", (method_id,))
        replacement = await (await connection.execute(
            "SELECT id FROM staff_payment_methods WHERE staff_id=? AND is_active=1 ORDER BY id LIMIT 1", (staff_id,)
        )).fetchone()
        if replacement:
            await connection.execute("UPDATE staff_payment_methods SET is_default=1 WHERE id=?", (replacement["id"],))
        referenced = await (await connection.execute(
            "SELECT 1 FROM payout_requests WHERE payment_method_id=? LIMIT 1", (method_id,)
        )).fetchone()
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()
    if object_key and not referenced:
        await asyncio.to_thread(r2_client().delete_object, Bucket=R2_BUCKET_NAME, Key=object_key)


async def upload_qris(staff_id, content, content_type):
    signatures = {
        "image/png": b"\x89PNG\r\n\x1a\n",
        "image/jpeg": b"\xff\xd8\xff",
        "image/webp": b"RIFF",
    }
    signature = signatures.get(content_type)
    if not signature or not content.startswith(signature) or len(content) > 5 * 1024 * 1024:
        raise ValueError("QRIS harus berupa PNG, JPG, atau WebP valid dengan ukuran maksimal 5 MB.")
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[content_type]
    object_key = f"payment-methods/{staff_id}/pending/{secrets.token_urlsafe(18)}.{extension}"
    await asyncio.to_thread(
        r2_client().put_object, Bucket=R2_BUCKET_NAME, Key=object_key,
        Body=content, ContentType=content_type,
        Metadata={"purpose": "staff-payment-qris", "staff-id": str(staff_id)},
    )
    return object_key


async def create_qris_method(staff_id, provider, account_name, content, content_type):
    """Validate/upload QRIS, then move it under the permanent method-id prefix."""
    pending_key = await upload_qris(staff_id, content, content_type)
    method_id = None
    try:
        method_id = await create_method(
            staff_id, "qris", provider, account_name, qris_object_key=pending_key
        )
        extension = pending_key.rsplit(".", 1)[-1]
        final_key = f"payment-methods/{staff_id}/{method_id}/{secrets.token_urlsafe(18)}.{extension}"
        client = r2_client()
        await asyncio.to_thread(
            client.copy_object, Bucket=R2_BUCKET_NAME,
            CopySource={"Bucket": R2_BUCKET_NAME, "Key": pending_key},
            Key=final_key, MetadataDirective="COPY",
        )
        await asyncio.to_thread(client.delete_object, Bucket=R2_BUCKET_NAME, Key=pending_key)
        connection = await _db()
        try:
            await connection.execute(
                "UPDATE staff_payment_methods SET qris_object_key=? WHERE id=?",
                (final_key, method_id),
            )
            await connection.commit()
        finally:
            await connection.close()
        return method_id
    except Exception:
        try:
            await asyncio.to_thread(r2_client().delete_object, Bucket=R2_BUCKET_NAME, Key=pending_key)
        except Exception:
            pass
        if method_id:
            connection = await _db()
            try:
                await connection.execute("DELETE FROM staff_payment_methods WHERE id=?", (method_id,))
                await connection.commit()
            finally:
                await connection.close()
        raise


async def qris_download_url(object_key, expires=600):
    return await asyncio.to_thread(
        r2_client().generate_presigned_url, "get_object",
        Params={"Bucket": R2_BUCKET_NAME, "Key": object_key}, ExpiresIn=min(expires, 600),
    )


def scheduled_cycles(today=None):
    today = today or datetime.now(ZoneInfo("Asia/Jakarta")).date()
    cycles = []
    current_19 = date(today.year, today.month, 19)
    previous_month_end = date(today.year, today.month, 1) - timedelta(days=1)
    current_4 = date(today.year, today.month, 4)
    if today >= current_19:
        cycles.append((f"{today:%Y-%m}-19", date(today.year, today.month, 1), date(today.year, today.month, 15)))
    if today >= current_4:
        cycles.append((f"{today:%Y-%m}-04", date(previous_month_end.year, previous_month_end.month, 16), previous_month_end))
    # Include one previous cycle so restart downtime is caught up safely.
    previous_19 = date(previous_month_end.year, previous_month_end.month, 19)
    cycles.append((f"{previous_19:%Y-%m}-19", date(previous_19.year, previous_19.month, 1), date(previous_19.year, previous_19.month, 15)))
    return cycles


def _method_snapshot(method):
    if not method:
        return {
            "method_type": None, "provider": None, "account_name": None,
            "account_number": None, "qris_object_key": None,
        }
    return {
        "method_type": method["method_type"], "provider": method["provider"],
        "account_name": method["account_name"],
        "account_number": decrypt_value(method["account_encrypted"]) if method["account_encrypted"] else None,
        "qris_object_key": method["qris_object_key"],
    }


async def create_payout(staff_id, method_id=None, payout_type="instant", cutoff_start=None, cutoff_end=None, cycle_key=None, actor_id=0):
    connection = await _db()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        method = None
        if method_id:
            method = await (await connection.execute("""SELECT * FROM staff_payment_methods
                WHERE id=? AND staff_id=? AND is_active=1""", (method_id, staff_id))).fetchone()
        if payout_type == "instant" and not method:
            raise ValueError("Metode pembayaran tidak ditemukan.")
        clauses = ["a.staff_id=?", "a.status='approved'",
                   "NOT EXISTS(SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id)"]
        params = [staff_id]
        if cutoff_start and cutoff_end:
            clauses.append("date(a.approved_at) BETWEEN ? AND ?")
            params.extend([str(cutoff_start), str(cutoff_end)])
        items = await (await connection.execute(f"""SELECT a.* FROM assignments a
            WHERE {' AND '.join(clauses)} ORDER BY a.id""", params)).fetchall()
        if not items:
            raise ValueError("Tidak ada saldo approved yang tersedia untuk dicairkan.")
        snapshot = _method_snapshot(method)
        payout_status = "issued" if method else "awaiting_method"
        period = (cutoff_end or datetime.now(ZoneInfo("Asia/Jakarta")).date()).strftime("%Y-%m")
        number = f"RYU-{period.replace('-', '')}-{staff_id}-{secrets.token_hex(2).upper()}"
        chapter_count = sum(item["chapter_count"] or 1 for item in items)
        total = sum(item["final_rate"] for item in items)
        invoice = await connection.execute("""INSERT INTO dashboard_invoices
            (invoice_number,staff_id,period,chapter_count,total_amount,status,issued_by,invoice_type)
            VALUES(?,?,?,?,?,'issued',?,?)""",
            (number, staff_id, period, chapter_count, total, actor_id, payout_type))
        invoice_id = invoice.lastrowid
        await connection.executemany("""INSERT INTO dashboard_invoice_items
            (invoice_id,assignment_id,manga,chapter,role,amount,assigned_at,approved_at,chapter_count,rate_per_chapter)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", [(
                invoice_id, item["id"], item["manga"], item["chapter"], item["role"], item["final_rate"],
                item["assigned_at"], item["approved_at"], item["chapter_count"] or 1,
                item["rate_per_chapter"] or item["final_rate"],
            ) for item in items])
        await connection.executemany(
            "INSERT INTO dashboard_assignment_billing(assignment_id,invoice_id) VALUES(?,?)",
            [(item["id"], invoice_id) for item in items],
        )
        cursor = await connection.execute("""INSERT INTO payout_requests
            (staff_id,payout_type,cycle_key,cutoff_start,cutoff_end,invoice_id,payment_method_id,
             method_snapshot_encrypted,chapter_count,total_amount,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
                staff_id, payout_type, cycle_key, str(cutoff_start) if cutoff_start else None,
                str(cutoff_end) if cutoff_end else None, invoice_id, method_id,
                encrypt_value(json.dumps(snapshot)), chapter_count, total, payout_status,
            ))
        await connection.commit()
        return {"id": cursor.lastrowid, "invoice_id": invoice_id, "invoice_number": number,
                "chapter_count": chapter_count, "total_amount": total, "snapshot": snapshot,
                "staff_id": staff_id, "cycle_key": cycle_key, "status": payout_status}
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()


async def ensure_payout_for_invoice(invoice_id):
    """Wrap a legacy/manual issued invoice so every payment uses the shared payout flow."""
    connection = await _db()
    try:
        existing = await (await connection.execute(
            "SELECT id FROM payout_requests WHERE invoice_id=?", (invoice_id,)
        )).fetchone()
        if existing:
            return existing["id"]
        invoice = await (await connection.execute(
            "SELECT * FROM dashboard_invoices WHERE id=? AND status='issued'", (invoice_id,)
        )).fetchone()
        if not invoice:
            raise ValueError("Invoice tidak ditemukan atau sudah diproses.")
        method = await (await connection.execute("""SELECT * FROM staff_payment_methods
            WHERE staff_id=? AND is_active=1 AND is_default=1 ORDER BY id LIMIT 1""",
            (invoice["staff_id"],))).fetchone()
        snapshot = _method_snapshot(method)
        status = "issued" if method else "awaiting_method"
        cursor = await connection.execute("""INSERT INTO payout_requests
            (staff_id,payout_type,invoice_id,payment_method_id,method_snapshot_encrypted,
             chapter_count,total_amount,status)
            VALUES(?,'instant',?,?,?,?,?,?)""", (
                invoice["staff_id"], invoice_id, method["id"] if method else None,
                encrypt_value(json.dumps(snapshot)), invoice["chapter_count"], invoice["total_amount"], status,
            ))
        await connection.commit()
        return cursor.lastrowid
    finally:
        await connection.close()


async def attach_payment_method_to_waiting(staff_id, preferred_method_id=None):
    connection = await _db()
    try:
        method = None
        if preferred_method_id:
            method = await (await connection.execute("""SELECT * FROM staff_payment_methods
                WHERE id=? AND staff_id=? AND is_active=1""", (preferred_method_id, staff_id))).fetchone()
        if not method:
            method = await (await connection.execute("""SELECT * FROM staff_payment_methods
                WHERE staff_id=? AND is_active=1 AND is_default=1 ORDER BY id LIMIT 1""", (staff_id,))).fetchone()
        if not method:
            return 0
        cursor = await connection.execute("""UPDATE payout_requests SET payment_method_id=?,
            method_snapshot_encrypted=?,status='issued'
            WHERE staff_id=? AND status='awaiting_method'""",
            (method["id"], encrypt_value(json.dumps(_method_snapshot(method))), staff_id))
        await connection.commit()
        return cursor.rowcount
    finally:
        await connection.close()


async def _wrap_existing_invoice(staff_id, method, cycle_key, start, end):
    """Reuse a legacy/manual issued invoice and add other eligible unbilled cutoff items."""
    connection = await _db()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        invoice = await (await connection.execute("""SELECT DISTINCT i.* FROM dashboard_invoices i
            JOIN dashboard_invoice_items x ON x.invoice_id=i.id
            WHERE i.staff_id=? AND i.status='issued'
              AND date(x.approved_at) BETWEEN ? AND ?
              AND NOT EXISTS(SELECT 1 FROM payout_requests p WHERE p.invoice_id=i.id)
            ORDER BY i.issued_at DESC LIMIT 1""", (staff_id, str(start), str(end)))).fetchone()
        if not invoice:
            await connection.rollback()
            return None
        additions = await (await connection.execute("""SELECT a.* FROM assignments a
            WHERE a.staff_id=? AND a.status='approved' AND date(a.approved_at) BETWEEN ? AND ?
              AND NOT EXISTS(SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id)
            ORDER BY a.id""", (staff_id, str(start), str(end)))).fetchall()
        if additions:
            await connection.executemany("""INSERT INTO dashboard_invoice_items
                (invoice_id,assignment_id,manga,chapter,role,amount,assigned_at,approved_at,chapter_count,rate_per_chapter)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", [(
                    invoice["id"], item["id"], item["manga"], item["chapter"], item["role"], item["final_rate"],
                    item["assigned_at"], item["approved_at"], item["chapter_count"] or 1,
                    item["rate_per_chapter"] or item["final_rate"],
                ) for item in additions])
            await connection.executemany(
                "INSERT INTO dashboard_assignment_billing(assignment_id,invoice_id) VALUES(?,?)",
                [(item["id"], invoice["id"]) for item in additions],
            )
        totals = await (await connection.execute("""SELECT SUM(chapter_count) chapters,SUM(amount) total
            FROM dashboard_invoice_items WHERE invoice_id=?""", (invoice["id"],))).fetchone()
        await connection.execute(
            "UPDATE dashboard_invoices SET chapter_count=?,total_amount=?,invoice_type='scheduled' WHERE id=?",
            (totals["chapters"], totals["total"], invoice["id"]))
        snapshot = _method_snapshot(method)
        status = "issued" if method else "awaiting_method"
        cursor = await connection.execute("""INSERT INTO payout_requests
            (staff_id,payout_type,cycle_key,cutoff_start,cutoff_end,invoice_id,payment_method_id,
             method_snapshot_encrypted,chapter_count,total_amount,status)
            VALUES(?,'scheduled',?,?,?,?,?,?,?,?,?)""", (
                staff_id, cycle_key, str(start), str(end), invoice["id"], method["id"] if method else None,
                encrypt_value(json.dumps(snapshot)), totals["chapters"], totals["total"], status,
            ))
        await connection.commit()
        return {"id": cursor.lastrowid, "invoice_id": invoice["id"], "invoice_number": invoice["invoice_number"],
                "chapter_count": totals["chapters"], "total_amount": totals["total"], "staff_id": staff_id,
                "cycle_key": cycle_key, "status": status}
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()


async def create_due_scheduled_payouts(today=None):
    created = []
    for cycle_key, start, end in scheduled_cycles(today):
        connection = await _db()
        try:
            staff_rows = await (await connection.execute("""SELECT DISTINCT a.staff_id
                FROM assignments a WHERE a.status='approved' AND date(a.approved_at) BETWEEN ? AND ?""",
                (str(start), str(end)))).fetchall()
        finally:
            await connection.close()
        for row in staff_rows:
            existing = await _db()
            try:
                already = await (await existing.execute(
                    "SELECT id FROM payout_requests WHERE cycle_key=? AND staff_id=?",
                    (cycle_key, row["staff_id"]))).fetchone()
            finally:
                await existing.close()
            if already:
                await attach_payment_method_to_waiting(row["staff_id"])
                continue
            methods = await list_methods(row["staff_id"])
            default = next((item for item in methods if item["is_default"]), None)
            try:
                result = await _wrap_existing_invoice(row["staff_id"], default, cycle_key, start, end)
                if not result:
                    result = await create_payout(
                        row["staff_id"], default["id"] if default else None,
                        "scheduled", start, end, cycle_key,
                    )
                if not default:
                    result["missing_method"] = True
                created.append(result)
            except (ValueError, aiosqlite.IntegrityError):
                pass
    return created


async def list_payouts(status=None):
    connection = await _db()
    try:
        where, params = (" WHERE p.status=?", [status]) if status else ("", [])
        rows = await (await connection.execute(f"""SELECT p.*,i.invoice_number
            FROM payout_requests p JOIN dashboard_invoices i ON i.id=p.invoice_id
            {where} ORDER BY p.requested_at DESC LIMIT 200""", params)).fetchall()
        return [dict(row) for row in rows]
    finally:
        await connection.close()


async def list_staff_payouts(staff_id, limit=10):
    connection = await _db()
    try:
        rows = await (await connection.execute("""SELECT p.*,i.invoice_number
            FROM payout_requests p JOIN dashboard_invoices i ON i.id=p.invoice_id
            WHERE p.staff_id=? ORDER BY p.requested_at DESC LIMIT ?""", (staff_id, limit))).fetchall()
        return [dict(row) for row in rows]
    finally:
        await connection.close()


async def payout_detail(payout_id, include_sensitive=False):
    connection = await _db()
    try:
        row = await (await connection.execute("""SELECT p.*,i.invoice_number,i.period,i.paid_at
            FROM payout_requests p JOIN dashboard_invoices i ON i.id=p.invoice_id WHERE p.id=?""",
            (payout_id,))).fetchone()
        if not row:
            return None
        items = await (await connection.execute("""SELECT * FROM dashboard_invoice_items
            WHERE invoice_id=? ORDER BY assignment_id""", (row["invoice_id"],))).fetchall()
    finally:
        await connection.close()
    result = dict(row)
    snapshot = json.loads(decrypt_value(result.pop("method_snapshot_encrypted")))
    if not include_sensitive and snapshot.get("account_number"):
        snapshot["account_number"] = mask_account(snapshot["account_number"])
    result["method"] = snapshot
    result["items"] = [dict(item) for item in items]
    return result


async def pay_payout(payout_id, actor_id):
    connection = await _db()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        payout = await (await connection.execute(
            "SELECT * FROM payout_requests WHERE id=? AND status='issued'", (payout_id,)
        )).fetchone()
        if not payout:
            raise ValueError("Permintaan tidak ditemukan atau sudah diproses.")
        ids = [row["assignment_id"] for row in await (await connection.execute(
            "SELECT assignment_id FROM dashboard_invoice_items WHERE invoice_id=?", (payout["invoice_id"],)
        )).fetchall()]
        placeholders = ",".join("?" for _ in ids)
        period = (await (await connection.execute(
            "SELECT period FROM dashboard_invoices WHERE id=?", (payout["invoice_id"],)
        )).fetchone())["period"]
        await connection.execute(
            f"UPDATE assignments SET status='paid',paid_period=? WHERE status='approved' AND id IN ({placeholders})",
            [period, *ids],
        )
        await connection.execute(
            "UPDATE dashboard_invoices SET status='paid',paid_at=CURRENT_TIMESTAMP WHERE id=?",
            (payout["invoice_id"],),
        )
        await connection.execute("""INSERT INTO payments(staff_id,period,total_amount,chapter_count,status,paid_at)
            VALUES(?,?,?,?, 'paid',CURRENT_TIMESTAMP)""",
            (payout["staff_id"], period, payout["total_amount"], payout["chapter_count"]))
        await connection.execute("""UPDATE payout_requests SET status='paid',processed_at=CURRENT_TIMESTAMP,
            processed_by=? WHERE id=?""", (actor_id, payout_id))
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()
    return await payout_detail(payout_id, include_sensitive=True)


async def record_invoice_delivery(payout_id, message_id=None, error=None):
    connection = await _db()
    try:
        await connection.execute("""UPDATE payout_requests
            SET invoice_send_attempts=COALESCE(invoice_send_attempts,0)+1,
                invoice_sent_at=CASE WHEN ? IS NULL THEN CURRENT_TIMESTAMP ELSE invoice_sent_at END,
                invoice_message_id=CASE WHEN ? IS NULL THEN ? ELSE invoice_message_id END,
                invoice_send_error=?
            WHERE id=?""", (error, error, str(message_id) if message_id else None, error, payout_id))
        await connection.commit()
    finally:
        await connection.close()


async def reject_payout(payout_id, actor_id, reason):
    if not reason.strip():
        raise ValueError("Alasan penolakan wajib diisi.")
    connection = await _db()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        payout = await (await connection.execute(
            "SELECT * FROM payout_requests WHERE id=? AND status='issued'", (payout_id,)
        )).fetchone()
        if not payout:
            raise ValueError("Permintaan tidak ditemukan atau sudah diproses.")
        await connection.execute("DELETE FROM dashboard_assignment_billing WHERE invoice_id=?", (payout["invoice_id"],))
        await connection.execute("""UPDATE dashboard_invoices SET status='void',voided_at=CURRENT_TIMESTAMP,
            voided_by=? WHERE id=?""", (actor_id, payout["invoice_id"]))
        await connection.execute("""UPDATE payout_requests SET status='rejected',rejection_reason=?,
            processed_at=CURRENT_TIMESTAMP,processed_by=? WHERE id=?""", (reason.strip(), actor_id, payout_id))
        await connection.commit()
        return dict(payout)
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()

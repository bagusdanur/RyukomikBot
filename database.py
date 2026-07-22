import aiosqlite
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "ryukomik.db")


async def get_db() -> aiosqlite.Connection:
    """Get a concurrency-safe SQLite connection for Discord interactions."""
    db = await aiosqlite.connect(DB_PATH, timeout=30.0)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA busy_timeout = 30000")
    await db.execute("PRAGMA foreign_keys = ON")
    return db


async def setup_database():
    """Initialize database tables."""
    db = await get_db()
    try:
        # WAL lets panel reads continue while another interaction writes.
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA synchronous = NORMAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                manga TEXT NOT NULL,
                chapter TEXT NOT NULL,
                staff_id INTEGER,
                role TEXT NOT NULL,
                base_rate INTEGER NOT NULL,
                final_rate INTEGER NOT NULL,
                multiplier REAL NOT NULL DEFAULT 1.0,
                status TEXT NOT NULL DEFAULT 'open',
                gdrive_link TEXT,
                admin_notes TEXT,
                message_id INTEGER,
                ticket_channel_id INTEGER,
                claimed_at DATETIME,
                assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                submitted_at DATETIME,
                approved_at DATETIME,
                paid_period TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                period TEXT NOT NULL,
                total_amount INTEGER NOT NULL,
                chapter_count INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                paid_at DATETIME
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS payrates (
                role TEXT PRIMARY KEY,
                base_rate INTEGER NOT NULL CHECK(base_rate >= 0),
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.executemany(
            "INSERT OR IGNORE INTO payrates (role, base_rate) VALUES (?, ?)",
            (("TL", 3000), ("TS", 3000), ("TL+TS", 5000)),
        )
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(assignments)")).fetchall()}
        if "deadline_at" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN deadline_at DATETIME")
        
        await db.commit()
    finally:
        await db.close()


async def create_assignment(
    manga: str,
    chapter: str,
    role: str,
    base_rate: int,
    final_rate: int,
    multiplier: float,
    message_id: Optional[int] = None,
    ticket_channel_id: Optional[int] = None,
    staff_id: Optional[int] = None,
    deadline_at: Optional[str] = None,
) -> int:
    """Create a new assignment and return its ID."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            INSERT INTO assignments
                (manga, chapter, staff_id, role, base_rate, final_rate, multiplier,
                 status, message_id, ticket_channel_id, claimed_at, deadline_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            manga, chapter, staff_id, role, base_rate, final_rate, multiplier,
            "claimed" if staff_id else "open", message_id, ticket_channel_id,
            datetime.now().isoformat(timespec="seconds") if staff_id else None,
            deadline_at,
        ))
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def claim_assignment(assignment_id: int, staff_id: int) -> bool:
    """Claim an assignment. Returns True if successful."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            UPDATE assignments 
            SET staff_id = ?, status = 'claimed', claimed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'open'
        """, (staff_id, assignment_id))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def submit_assignment(assignment_id: int, gdrive_link: str, catatan: Optional[str] = None) -> bool:
    """Submit an assignment. Returns True if successful."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            UPDATE assignments 
            SET gdrive_link = ?, status = 'submitted', submitted_at = CURRENT_TIMESTAMP, admin_notes = COALESCE(?, admin_notes)
            WHERE id = ? AND status IN ('claimed', 'revision')
        """, (gdrive_link, catatan, assignment_id))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def approve_assignment(assignment_id: int) -> bool:
    """Approve an assignment. Returns True if successful."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            UPDATE assignments 
            SET status = 'approved', approved_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'submitted'
        """, (assignment_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def revise_assignment(assignment_id: int, catatan: str) -> bool:
    """Send assignment back for revision. Returns True if successful."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            UPDATE assignments 
            SET status = 'revision', admin_notes = ?
            WHERE id = ? AND status = 'submitted'
        """, (catatan, assignment_id))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def mark_paid(assignment_ids: List[int], period: str) -> bool:
    """Mark multiple assignments as paid. Returns True if successful."""
    if not assignment_ids:
        return False
    
    db = await get_db()
    try:
        placeholders = ",".join(["?" for _ in assignment_ids])
        cursor = await db.execute(f"""
            UPDATE assignments 
            SET status = 'paid', paid_period = ?
            WHERE id IN ({placeholders}) AND status = 'approved'
        """, [period] + assignment_ids)
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_assignment(assignment_id: int) -> Optional[Dict[str, Any]]:
    """Get assignment by ID."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,))
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        await db.close()


async def get_assignments_by_status(status: str) -> List[Dict[str, Any]]:
    """Get all assignments with a specific status."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM assignments WHERE status = ? ORDER BY assigned_at DESC", (status,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_assignments_by_staff(staff_id: int) -> List[Dict[str, Any]]:
    """Get all assignments for a specific staff member."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM assignments WHERE staff_id = ? ORDER BY assigned_at DESC",
            (staff_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_staff_stats(staff_id: int, period: Optional[str] = None) -> Dict[str, Any]:
    """Get staff statistics for a period."""
    db = await get_db()
    try:
        if period:
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'approved' THEN final_rate ELSE 0 END) as total_earned,
                    SUM(CASE WHEN status = 'paid' THEN final_rate ELSE 0 END) as total_paid,
                    SUM(CASE WHEN status IN ('open', 'claimed', 'submitted', 'revision') THEN 1 ELSE 0 END) as pending
                FROM assignments 
                WHERE staff_id = ? 
                  AND (
                    approved_at LIKE ?
                    OR paid_period = ?
                    OR (approved_at IS NULL AND assigned_at LIKE ?)
                  )
            """, (staff_id, f"{period}%", period, f"{period}%"))
        else:
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'approved' THEN final_rate ELSE 0 END) as total_earned,
                    SUM(CASE WHEN status = 'paid' THEN final_rate ELSE 0 END) as total_paid,
                    SUM(CASE WHEN status IN ('open', 'claimed', 'submitted', 'revision') THEN 1 ELSE 0 END) as pending
                FROM assignments 
                WHERE staff_id = ?
            """, (staff_id,))
        row = await cursor.fetchone()
        return dict(row) if row else {"total": 0, "total_earned": 0, "total_paid": 0, "pending": 0}
    finally:
        await db.close()


async def get_rekap(period: str) -> List[Dict[str, Any]]:
    """Get recap data for a period."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT 
                staff_id,
                COUNT(*) as chapter_count,
                SUM(final_rate) as total_amount
            FROM assignments 
            WHERE approved_at LIKE ? AND status = 'approved'
            GROUP BY staff_id
        """, (f"{period}%",))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_role_payrate(role: str) -> int:
    """Return the persisted base rate for an assignment role."""
    defaults = {"TL": 3000, "TS": 3000, "TL+TS": 5000}
    db = await get_db()
    try:
        cursor = await db.execute("SELECT base_rate FROM payrates WHERE role = ?", (role,))
        row = await cursor.fetchone()
        return int(row[0]) if row else defaults.get(role, 3000)
    finally:
        await db.close()


async def set_role_payrate(role: str, base_rate: int) -> bool:
    """Persist a base rate used by future non-override assignments."""
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO payrates (role, base_rate, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(role) DO UPDATE SET
                base_rate = excluded.base_rate,
                updated_at = CURRENT_TIMESTAMP
            """,
            (role, base_rate),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def set_assignment_ticket_channel(assignment_id: int, ticket_channel_id: int) -> bool:
    """Store the staff ticket channel for an assignment."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE assignments SET ticket_channel_id = ? WHERE id = ?",
            (ticket_channel_id, assignment_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_approved_assignments_for_payment(staff_id: int, period: str) -> List[Dict[str, Any]]:
    """Get approved, unpaid assignments for a staff member in an approval period."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT *
            FROM assignments
            WHERE staff_id = ?
              AND status = 'approved'
              AND approved_at LIKE ?
            ORDER BY approved_at DESC
        """, (staff_id, f"{period}%"))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def create_payment(staff_id: int, period: str, total_amount: int, chapter_count: int) -> int:
    """Create a payment record and return its ID."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            INSERT INTO payments (staff_id, period, total_amount, chapter_count, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (staff_id, period, total_amount, chapter_count))
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def mark_payment_paid(payment_id: int) -> bool:
    """Mark a payment as paid. Returns True if successful."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            UPDATE payments 
            SET status = 'paid', paid_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending'
        """, (payment_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_pending_payments() -> List[Dict[str, Any]]:
    """Get all pending payments."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM payments WHERE status = 'pending' ORDER BY id DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()

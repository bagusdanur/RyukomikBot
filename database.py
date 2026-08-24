import aiosqlite
import os
import json
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

        await db.execute("""
            CREATE TABLE IF NOT EXISTS payrates (
                role TEXT PRIMARY KEY,
                base_rate INTEGER NOT NULL CHECK(base_rate >= 0),
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS assignment_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                actor_id TEXT,
                detail TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(assignment_id) REFERENCES assignments(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminder_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reminder_key TEXT NOT NULL UNIQUE,
                assignment_id INTEGER,
                recipient_type TEXT NOT NULL,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(assignment_id) REFERENCES assignments(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recruitment_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                applicant_id INTEGER NOT NULL,
                position TEXT NOT NULL,
                ticket_channel_id INTEGER NOT NULL,
                gdrive_link TEXT NOT NULL,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'submitted',
                review_message_id INTEGER,
                submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at DATETIME,
                reviewed_by INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recruitment_position_settings (
                position TEXT PRIMARY KEY CHECK(position IN ('TL','TS','TL+TS')),
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT
            )
        """)
        await db.executemany(
            """INSERT OR IGNORE INTO recruitment_position_settings(position,enabled)
               VALUES(?,1)""",
            (("TL",), ("TS",), ("TL+TS",)),
        )
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recruitment_material_settings (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                test_url TEXT NOT NULL,
                tl_example_url TEXT NOT NULL,
                ts_assets_url TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS staff_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                requires_answer INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed_at DATETIME
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS staff_question_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                staff_id INTEGER NOT NULL,
                answer TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(question_id, staff_id),
                FOREIGN KEY(question_id) REFERENCES staff_questions(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deadline_extension_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                staff_id INTEGER NOT NULL,
                old_deadline TEXT NOT NULL,
                requested_deadline TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                reviewed_at DATETIME,
                reviewed_by INTEGER,
                FOREIGN KEY(assignment_id) REFERENCES assignments(id)
            )
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_deadline_extension_pending
            ON deadline_extension_requests(assignment_id) WHERE status='pending'
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_recruitment_active_applicant
            ON recruitment_submissions(applicant_id)
            WHERE status = 'submitted'
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                host_id INTEGER NOT NULL,
                prize TEXT NOT NULL,
                description TEXT,
                winner_count INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                requirement_role_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                ends_at DATETIME NOT NULL,
                ended_at DATETIME,
                winners_json TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                giveaway_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(giveaway_id, user_id),
                FOREIGN KEY(giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_giveaways_status ON giveaways(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_giveaway_entries_lookup ON giveaway_entries(giveaway_id, user_id)
        """)
        await db.executemany(
            "INSERT OR IGNORE INTO payrates (role, base_rate) VALUES (?, ?)",
            (("TL", 4000), ("TS", 5000), ("TL+TS", 9000)),
        )
        payrate_columns = {
            row[1] for row in await (await db.execute("PRAGMA table_info(payrates)")).fetchall()
        }
        migrate_payrate_ranges = "min_rate" not in payrate_columns
        if "min_rate" not in payrate_columns:
            await db.execute("ALTER TABLE payrates ADD COLUMN min_rate INTEGER")
        if "max_rate" not in payrate_columns:
            await db.execute("ALTER TABLE payrates ADD COLUMN max_rate INTEGER")
        if migrate_payrate_ranges:
            await db.executemany(
                """UPDATE payrates SET base_rate=?, min_rate=?, max_rate=?
                   WHERE role=?""",
                (
                    (4000, 4000, 8000, "TL"),
                    (5000, 5000, 10000, "TS"),
                    (9000, 9000, 18000, "TL+TS"),
                ),
            )
        else:
            await db.execute(
                "UPDATE payrates SET min_rate=COALESCE(min_rate,base_rate), max_rate=COALESCE(max_rate,base_rate)"
            )
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(assignments)")).fetchall()}
        if "deadline_at" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN deadline_at DATETIME")
        if "chapters" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN chapters TEXT")
        if "chapter_count" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN chapter_count INTEGER NOT NULL DEFAULT 1")
        if "rate_per_chapter" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN rate_per_chapter INTEGER")
        if "review_message_id" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN review_message_id INTEGER")
        if "raw_mode" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN raw_mode TEXT NOT NULL DEFAULT 'editor_safe'")
        if "raw_source" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN raw_source TEXT")
        if "raw_manga_id" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN raw_manga_id TEXT")
        if "raw_pack_mode" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN raw_pack_mode TEXT NOT NULL DEFAULT 'normal'")
        await db.execute("""
            UPDATE assignments
            SET chapters = COALESCE(chapters, json_array(chapter)),
                chapter_count = COALESCE(NULLIF(chapter_count, 0), 1),
                rate_per_chapter = COALESCE(rate_per_chapter, final_rate)
            WHERE chapters IS NULL OR rate_per_chapter IS NULL OR chapter_count IS NULL OR chapter_count=0
        """)
        await db.execute("""
            INSERT INTO assignment_events (assignment_id,event_type,actor_id,detail,created_at)
            SELECT a.id,
                   CASE WHEN a.status='open' THEN 'created' ELSE 'assigned' END,
                   CAST(a.staff_id AS TEXT),'Riwayat awal dimigrasikan.',a.assigned_at
            FROM assignments a
            WHERE NOT EXISTS (
                SELECT 1 FROM assignment_events e WHERE e.assignment_id=a.id
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_assignments_status_time ON assignments(status,assigned_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_assignments_staff_status ON assignments(staff_id,status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_assignments_deadline_status ON assignments(deadline_at,status)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tl_ts_handoffs (
                tl_assignment_id INTEGER PRIMARY KEY,
                ts_staff_id INTEGER NOT NULL,
                ts_rate_per_chapter INTEGER NOT NULL,
                deadline_at DATETIME,
                created_by TEXT,
                ts_assignment_id INTEGER UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                activated_at DATETIME,
                FOREIGN KEY(tl_assignment_id) REFERENCES assignments(id),
                FOREIGN KEY(ts_assignment_id) REFERENCES assignments(id)
            )
        """)
        
        await db.commit()
    finally:
        await db.close()

    # Kept in a separate module so pair workflow transactions stay isolated.
    from pair_workflow import setup_pair_tables
    await setup_pair_tables()


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
    chapters: Optional[List[str]] = None,
    rate_per_chapter: Optional[int] = None,
    raw_mode: str = "editor_safe",
    raw_source: Optional[str] = None,
    raw_manga_id: Optional[str] = None,
    raw_pack_mode: str = "normal",
) -> int:
    """Create a new assignment and return its ID."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            INSERT INTO assignments
                (manga, chapter, staff_id, role, base_rate, final_rate, multiplier,
                 status, message_id, ticket_channel_id, claimed_at, deadline_at,
                 chapters, chapter_count, rate_per_chapter, raw_mode, raw_source, raw_manga_id,
                 raw_pack_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            manga, chapter, staff_id, role, base_rate, final_rate, multiplier,
            "claimed" if staff_id else "open", message_id, ticket_channel_id,
            datetime.now().isoformat(timespec="seconds") if staff_id else None,
            deadline_at, json.dumps(chapters or [chapter], ensure_ascii=False),
            len(chapters or [chapter]), rate_per_chapter if rate_per_chapter is not None else final_rate,
            raw_mode if raw_mode in {"editor_safe", "original"} else "editor_safe",
            raw_source, raw_manga_id,
            raw_pack_mode if raw_pack_mode in {"normal", "merge_16000"} else "normal",
        ))
        await db.commit()
        await add_assignment_event(
            cursor.lastrowid, "assigned" if staff_id else "created", staff_id,
            "Tugas diberikan langsung." if staff_id else "Tugas dibuka untuk claim.",
        )
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
        if cursor.rowcount:
            await add_assignment_event(assignment_id, "claimed", staff_id, "Tugas diklaim staff.")
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
        if cursor.rowcount:
            await add_assignment_event(assignment_id, "submitted", None, catatan or "Hasil dikirim untuk review.")
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
        if cursor.rowcount:
            await add_assignment_event(assignment_id, "approved", None, "Hasil disetujui.")
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
        if cursor.rowcount:
            await add_assignment_event(assignment_id, "revision", None, catatan)
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
        if cursor.rowcount:
            for assignment_id in assignment_ids:
                await add_assignment_event(assignment_id, "paid", None, f"Pembayaran periode {period}.")
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
            # Each assignment is attributed to exactly ONE "effective period" so it
            # can never be counted in two months at once:
            #   - paid      -> paid_period (the month it was actually disbursed)
            #   - approved  -> month of approved_at (completed, awaiting payout)
            #   - otherwise -> month of assigned_at (still in progress)
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'approved' THEN final_rate ELSE 0 END) as total_earned,
                    SUM(CASE WHEN status = 'paid' THEN final_rate ELSE 0 END) as total_paid,
                    SUM(CASE WHEN status IN ('approved', 'paid') THEN final_rate ELSE 0 END) as total_completed_amount,
                    SUM(CASE WHEN status IN ('approved', 'paid') THEN COALESCE(chapter_count, 1) ELSE 0 END) as completed_chapters,
                    SUM(CASE WHEN status = 'pair_waiting' THEN 1 ELSE 0 END) as pair_pending,
                    SUM(CASE WHEN status IN ('open', 'claimed', 'submitted', 'revision') THEN 1 ELSE 0 END) as pending
                FROM assignments 
                WHERE staff_id = ? 
                  AND (
                    CASE
                        WHEN status = 'paid' THEN paid_period
                        WHEN approved_at IS NOT NULL THEN substr(approved_at, 1, 7)
                        ELSE substr(assigned_at, 1, 7)
                    END
                  ) = ?
            """, (staff_id, period))
        else:
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'approved' THEN final_rate ELSE 0 END) as total_earned,
                    SUM(CASE WHEN status = 'paid' THEN final_rate ELSE 0 END) as total_paid,
                    SUM(CASE WHEN status IN ('approved', 'paid') THEN final_rate ELSE 0 END) as total_completed_amount,
                    SUM(CASE WHEN status IN ('approved', 'paid') THEN COALESCE(chapter_count, 1) ELSE 0 END) as completed_chapters,
                    SUM(CASE WHEN status = 'pair_waiting' THEN 1 ELSE 0 END) as pair_pending,
                    SUM(CASE WHEN status IN ('open', 'claimed', 'submitted', 'revision') THEN 1 ELSE 0 END) as pending
                FROM assignments 
                WHERE staff_id = ?
            """, (staff_id,))
        row = await cursor.fetchone()
        result = dict(row) if row else {}
        return {
            "total": result.get("total") or 0,
            "total_earned": result.get("total_earned") or 0,
            "total_paid": result.get("total_paid") or 0,
            "total_completed_amount": result.get("total_completed_amount") or 0,
            "completed_chapters": result.get("completed_chapters") or 0,
            "pair_pending": result.get("pair_pending") or 0,
            "pending": result.get("pending") or 0,
        }
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


async def create_tl_ts_pair(
    *, manga: str, chapter: str, chapters: List[str], tl_staff_id: int,
    ts_staff_id: int, tl_rate_per_chapter: int, ts_rate_per_chapter: int,
    deadline_at: Optional[str], created_by: Optional[int] = None,
) -> int:
    """Create the TL task now; reserve TS until the TL result is approved."""
    tl_assignment_id = await create_assignment(
        manga=manga, chapter=chapter, chapters=chapters, role="TL",
        base_rate=tl_rate_per_chapter, rate_per_chapter=tl_rate_per_chapter,
        final_rate=tl_rate_per_chapter * len(chapters), multiplier=1.0,
        staff_id=tl_staff_id, deadline_at=deadline_at,
    )
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO tl_ts_handoffs
               (tl_assignment_id,ts_staff_id,ts_rate_per_chapter,deadline_at,created_by)
               VALUES(?,?,?,?,?)""",
            (tl_assignment_id, ts_staff_id, ts_rate_per_chapter, deadline_at,
             str(created_by) if created_by else None),
        )
        await db.commit()
        await add_assignment_event(
            tl_assignment_id, "pair_created", created_by,
            f"Pair TL → TS disiapkan untuk staff {ts_staff_id}.",
        )
        return tl_assignment_id
    finally:
        await db.close()


async def activate_ts_handoff(tl_assignment_id: int) -> Optional[Dict[str, Any]]:
    """Create exactly one TS task after its paired TL has been approved."""
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute(
            """SELECT h.*,a.manga,a.chapter,a.chapters,a.chapter_count,a.gdrive_link
               FROM tl_ts_handoffs h JOIN assignments a ON a.id=h.tl_assignment_id
               WHERE h.tl_assignment_id=? AND a.status='approved'""",
            (tl_assignment_id,),
        )).fetchone()
        if not row or row["ts_assignment_id"]:
            await db.rollback()
            return None
        chapters = json.loads(row["chapters"] or "[]") or [row["chapter"]]
        handoff_note = f"Pair TL #{tl_assignment_id} sudah disetujui. Hasil TL: {row['gdrive_link'] or 'Link tidak tersedia'}"
        cursor = await db.execute(
            """INSERT INTO assignments
               (manga,chapter,staff_id,role,base_rate,final_rate,multiplier,status,
                claimed_at,deadline_at,chapters,chapter_count,rate_per_chapter,admin_notes)
               VALUES(?,?,?,?,?,?,1.0,'claimed',?,?,?,?,?,?)""",
            (row["manga"], row["chapter"], row["ts_staff_id"], "TS",
             row["ts_rate_per_chapter"], row["ts_rate_per_chapter"] * len(chapters),
             datetime.now().isoformat(timespec="seconds"), row["deadline_at"],
             json.dumps(chapters, ensure_ascii=False), len(chapters),
             row["ts_rate_per_chapter"], handoff_note),
        )
        ts_assignment_id = cursor.lastrowid
        await db.execute(
            "UPDATE tl_ts_handoffs SET ts_assignment_id=?,activated_at=CURRENT_TIMESTAMP WHERE tl_assignment_id=?",
            (ts_assignment_id, tl_assignment_id),
        )
        await db.commit()
        await add_assignment_event(ts_assignment_id, "activated_from_tl", None, handoff_note)
        result = dict(row)
        result.update({"id": ts_assignment_id, "staff_id": row["ts_staff_id"], "role": "TS",
                       "rate_per_chapter": row["ts_rate_per_chapter"],
                       "final_rate": row["ts_rate_per_chapter"] * len(chapters),
                       "admin_notes": handoff_note})
        return result
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def upsert_recruitment_submission(
    applicant_id: int,
    position: str,
    ticket_channel_id: int,
    gdrive_link: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or refresh the applicant's one active recruitment review."""
    db = await get_db()
    try:
        row = await (await db.execute(
            """SELECT * FROM recruitment_submissions
               WHERE applicant_id=? AND status='submitted'""",
            (applicant_id,),
        )).fetchone()
        if row:
            submission_id = int(row["id"])
            await db.execute(
                """UPDATE recruitment_submissions
                   SET position=?, ticket_channel_id=?, gdrive_link=?, notes=?,
                       submitted_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (position, ticket_channel_id, gdrive_link, notes, submission_id),
            )
        else:
            cursor = await db.execute(
                """INSERT INTO recruitment_submissions
                   (applicant_id,position,ticket_channel_id,gdrive_link,notes)
                   VALUES (?,?,?,?,?)""",
                (applicant_id, position, ticket_channel_id, gdrive_link, notes),
            )
            submission_id = int(cursor.lastrowid)
        await db.commit()
        result = await (await db.execute(
            "SELECT * FROM recruitment_submissions WHERE id=?",
            (submission_id,),
        )).fetchone()
        return dict(result)
    finally:
        await db.close()


async def get_recruitment_submission(submission_id: int) -> Optional[Dict[str, Any]]:
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT * FROM recruitment_submissions WHERE id=?",
            (submission_id,),
        )).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def set_recruitment_review_message(submission_id: int, message_id: int) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE recruitment_submissions SET review_message_id=? WHERE id=?",
            (message_id, submission_id),
        )
        await db.commit()
    finally:
        await db.close()

async def approve_recruitment_submission(submission_id: int, admin_id: int) -> bool:
    """Atomically finish one active recruitment review."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """UPDATE recruitment_submissions
               SET status='approved', reviewed_at=CURRENT_TIMESTAMP, reviewed_by=?
               WHERE id=? AND status='submitted'""",
            (admin_id, submission_id),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_recruitment_position_settings() -> Dict[str, bool]:
    """Return every recruitment position, defaulting safely to enabled."""
    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT position,enabled FROM recruitment_position_settings"
        )).fetchall()
        values = {str(row["position"]): bool(row["enabled"]) for row in rows}
        return {position: values.get(position, True) for position in ("TL", "TS", "TL+TS")}
    finally:
        await db.close()


async def set_recruitment_position_settings(
    settings: Dict[str, bool], updated_by: str | int
) -> Dict[str, bool]:
    """Atomically replace the enabled state for all supported positions."""
    normalized = {
        position: bool(settings.get(position, False))
        for position in ("TL", "TS", "TL+TS")
    }
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        for position, enabled in normalized.items():
            await db.execute(
                """INSERT INTO recruitment_position_settings
                   (position,enabled,updated_at,updated_by)
                   VALUES(?,?,CURRENT_TIMESTAMP,?)
                   ON CONFLICT(position) DO UPDATE SET
                     enabled=excluded.enabled,
                     updated_at=CURRENT_TIMESTAMP,
                     updated_by=excluded.updated_by""",
                (position, int(enabled), str(updated_by)),
            )
        await db.commit()
        return normalized
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def get_recruitment_material_settings(defaults: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Return dashboard-managed recruitment links, falling back to config values."""
    defaults = defaults or {}
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT test_url,tl_example_url,ts_assets_url,updated_at,updated_by "
            "FROM recruitment_material_settings WHERE id=1"
        )).fetchone()
        if row:
            return dict(row)
        return {
            "test_url": defaults.get("test_url", ""),
            "tl_example_url": defaults.get("tl_example_url", ""),
            "ts_assets_url": defaults.get("ts_assets_url", ""),
            "updated_at": None,
            "updated_by": None,
        }
    finally:
        await db.close()


async def set_recruitment_material_settings(
    links: Dict[str, str], updated_by: str | int
) -> Dict[str, Any]:
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO recruitment_material_settings
               (id,test_url,tl_example_url,ts_assets_url,updated_at,updated_by)
               VALUES(1,?,?,?,CURRENT_TIMESTAMP,?)
               ON CONFLICT(id) DO UPDATE SET
                 test_url=excluded.test_url,
                 tl_example_url=excluded.tl_example_url,
                 ts_assets_url=excluded.ts_assets_url,
                 updated_at=CURRENT_TIMESTAMP,
                 updated_by=excluded.updated_by""",
            (links["test_url"], links["tl_example_url"], links["ts_assets_url"], str(updated_by)),
        )
        await db.commit()
    finally:
        await db.close()
    return await get_recruitment_material_settings()


async def get_staff_question(question_id: int) -> Optional[Dict[str, Any]]:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT * FROM staff_questions WHERE id=?", (question_id,))).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def answer_staff_question(question_id: int, staff_id: int, answer: str) -> bool:
    db = await get_db()
    try:
        question = await (await db.execute(
            "SELECT status,requires_answer FROM staff_questions WHERE id=?", (question_id,)
        )).fetchone()
        if not question or question["status"] != "open" or not question["requires_answer"]:
            return False
        await db.execute(
            """INSERT INTO staff_question_responses(question_id,staff_id,answer)
               VALUES(?,?,?) ON CONFLICT(question_id,staff_id) DO UPDATE SET
               answer=excluded.answer,updated_at=CURRENT_TIMESTAMP""",
            (question_id, staff_id, answer.strip()),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def create_deadline_extension_request(
    assignment_id: int, staff_id: int, old_deadline: str,
    requested_deadline: str, reason: str,
) -> Optional[Dict[str, Any]]:
    db = await get_db()
    try:
        existing = await (await db.execute(
            "SELECT * FROM deadline_extension_requests WHERE assignment_id=? AND status='pending'",
            (assignment_id,),
        )).fetchone()
        if existing:
            return None
        cursor = await db.execute(
            """INSERT INTO deadline_extension_requests
               (assignment_id,staff_id,old_deadline,requested_deadline,reason)
               VALUES(?,?,?,?,?)""",
            (assignment_id, staff_id, old_deadline, requested_deadline, reason.strip()),
        )
        await db.commit()
        row = await (await db.execute(
            "SELECT * FROM deadline_extension_requests WHERE id=?", (cursor.lastrowid,)
        )).fetchone()
        return dict(row)
    finally:
        await db.close()


async def get_deadline_extension_request(request_id: int) -> Optional[Dict[str, Any]]:
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT * FROM deadline_extension_requests WHERE id=?", (request_id,)
        )).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def resolve_deadline_extension_request(request_id: int, admin_id: int, approved: bool) -> bool:
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute(
            "SELECT * FROM deadline_extension_requests WHERE id=? AND status='pending'", (request_id,)
        )).fetchone()
        if not row:
            await db.rollback()
            return False
        if approved:
            await db.execute(
                "UPDATE assignments SET deadline_at=? WHERE id=? AND status IN ('claimed','revision')",
                (row["requested_deadline"], row["assignment_id"]),
            )
        await db.execute(
            """UPDATE deadline_extension_requests SET status=?,reviewed_at=CURRENT_TIMESTAMP,reviewed_by=?
               WHERE id=?""",
            ("approved" if approved else "rejected", admin_id, request_id),
        )
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def clear_assignment_message(assignment_id: int) -> None:
    """Forget a task announcement after it has been removed from the public channel."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE assignments SET message_id = NULL WHERE id = ?",
            (assignment_id,),
        )
        await db.commit()
    finally:
        await db.close()


async def get_role_payrate(role: str) -> int:
    """Return the persisted base rate for an assignment role."""
    defaults = {"TL": 4000, "TS": 5000, "TL+TS": 9000}
    db = await get_db()
    try:
        cursor = await db.execute("SELECT base_rate FROM payrates WHERE role = ?", (role,))
        row = await cursor.fetchone()
        return int(row[0]) if row else defaults.get(role, 4000)
    finally:
        await db.close()


async def get_role_payrate_range(role: str) -> tuple[int, int]:
    defaults = {"TL": (4000, 8000), "TS": (5000, 10000), "TL+TS": (9000, 18000)}
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT base_rate,min_rate,max_rate FROM payrates WHERE role=?",
            (role,),
        )).fetchone()
        if not row:
            return defaults.get(role, defaults["TL"])
        return (
            int(row["min_rate"] or row["base_rate"]),
            int(row["max_rate"] or defaults.get(role, defaults["TL"])[1]),
        )
    finally:
        await db.close()


async def set_role_payrate(role: str, min_rate: int, max_rate: Optional[int] = None) -> bool:
    """Persist the allowed range used by future assignments."""
    max_rate = min_rate if max_rate is None else max_rate
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO payrates (role, base_rate, min_rate, max_rate, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(role) DO UPDATE SET
                base_rate = excluded.base_rate,
                min_rate = excluded.min_rate,
                max_rate = excluded.max_rate,
                updated_at = CURRENT_TIMESTAMP
            """,
            (role, min_rate, min_rate, max_rate),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def add_assignment_event(
    assignment_id: int, event_type: str, actor_id=None, detail: Optional[str] = None
) -> None:
    """Append an immutable assignment timeline entry."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO assignment_events (assignment_id,event_type,actor_id,detail)
               VALUES (?,?,?,?)""",
            (assignment_id, event_type, str(actor_id) if actor_id else None, detail),
        )
        await db.commit()
    finally:
        await db.close()


async def get_assignment_timeline(assignment_id: int) -> List[Dict[str, Any]]:
    db = await get_db()
    try:
        rows = await (await db.execute(
            """SELECT event_type,actor_id,detail,created_at FROM assignment_events
               WHERE assignment_id=? ORDER BY id ASC""",
            (assignment_id,),
        )).fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def claim_reminder(reminder_key: str, assignment_id: int, recipient_type: str) -> bool:
    """Reserve a reminder once so hourly loops and restarts cannot duplicate it."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT OR IGNORE INTO reminder_events
               (reminder_key,assignment_id,recipient_type) VALUES (?,?,?)""",
            (reminder_key, assignment_id, recipient_type),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_reminder_candidates() -> List[Dict[str, Any]]:
    db = await get_db()
    try:
        rows = await (await db.execute("""
            SELECT * FROM assignments
            WHERE
              (deadline_at IS NOT NULL AND status IN ('claimed','revision')
               AND date(deadline_at) <= date('now','+1 day'))
              OR
              (status='submitted' AND submitted_at IS NOT NULL
               AND datetime(submitted_at) <= datetime('now','-24 hours'))
            ORDER BY deadline_at ASC
        """)).fetchall()
        return [dict(row) for row in rows]
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


async def set_assignment_review_message(assignment_id: int, message_id: Optional[int]) -> None:
    """Keep the actionable staff-mod review card addressable by reminders."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE assignments SET review_message_id=? WHERE id=?",
            (message_id, assignment_id),
        )
        await db.commit()
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


async def get_revokable_assignments() -> List[Dict[str, Any]]:
    """Get all assignments that can be revoked (open or claimed)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM assignments WHERE status IN ('open', 'claimed') ORDER BY assigned_at DESC LIMIT 25"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def revoke_assignment(assignment_id: int, reason: str = None) -> bool:
    """Revoke an assignment and set its status to cancelled."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            UPDATE assignments 
            SET status = 'cancelled', admin_notes = ?
            WHERE id = ? AND status IN ('open', 'claimed')
        """, (reason, assignment_id))
        await db.commit()
        if cursor.rowcount:
            await add_assignment_event(assignment_id, "cancelled", None, f"Tugas ditarik oleh admin. Alasan: {reason or 'Tidak ada'}")
        return cursor.rowcount > 0
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Notification Preferences
# ---------------------------------------------------------------------------

NOTIF_TYPES = ("assignment", "deadline", "payout", "review", "revoke")
NOTIF_CHANNELS = ("dm", "ticket", "dashboard")


async def setup_notification_preferences():
    db = await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notification_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                notif_type TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'ticket',
                enabled INTEGER NOT NULL DEFAULT 1,
                reminder_hours INTEGER DEFAULT 24,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(staff_id, notif_type, channel)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_notif_prefs_staff
            ON notification_preferences(staff_id)
        """)
        await db.commit()
    finally:
        await db.close()


async def get_notification_preferences(staff_id: int) -> list[dict]:
    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT * FROM notification_preferences WHERE staff_id=? ORDER BY notif_type, channel",
            (staff_id,)
        )).fetchall()
        if rows:
            return [dict(r) for r in rows]
        # Return defaults if no preferences set
        defaults = []
        for ntype in NOTIF_TYPES:
            defaults.append({
                "staff_id": staff_id, "notif_type": ntype,
                "channel": "ticket", "enabled": 1, "reminder_hours": 24,
            })
        return defaults
    finally:
        await db.close()


async def set_notification_preference(
    staff_id: int, notif_type: str, channel: str, enabled: bool, reminder_hours: int = 24
) -> bool:
    db = await get_db()
    try:
        await db.execute("""
            INSERT INTO notification_preferences (staff_id, notif_type, channel, enabled, reminder_hours, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(staff_id, notif_type, channel)
            DO UPDATE SET enabled=excluded.enabled, reminder_hours=excluded.reminder_hours,
                          updated_at=CURRENT_TIMESTAMP
        """, (staff_id, notif_type, channel, int(enabled), reminder_hours))
        await db.commit()
        return True
    finally:
        await db.close()


async def bulk_set_preferences(staff_id: int, preferences: list[dict]) -> bool:
    db = await get_db()
    try:
        await db.execute("DELETE FROM notification_preferences WHERE staff_id=?", (staff_id,))
        for pref in preferences:
            await db.execute("""
                INSERT INTO notification_preferences (staff_id, notif_type, channel, enabled, reminder_hours)
                VALUES (?, ?, ?, ?, ?)
            """, (staff_id, pref["notif_type"], pref["channel"], int(pref.get("enabled", True)), pref.get("reminder_hours", 24)))
        await db.commit()
        return True
    finally:
        await db.close()


async def get_notif_channel(staff_id: int, notif_type: str) -> str | None:
    """Get the preferred notification channel for a staff+type. Returns None if disabled."""
    db = await get_db()
    try:
        row = await (await db.execute("""
            SELECT channel, enabled FROM notification_preferences
            WHERE staff_id=? AND notif_type=?
        """, (staff_id, notif_type))).fetchone()
        if row and not row["enabled"]:
            return None
        return row["channel"] if row else "ticket"  # default to ticket
    finally:
        await db.close()


# ==================== GIVEAWAYS ====================

async def create_giveaway(
    guild_id: int,
    channel_id: int,
    host_id: int,
    prize: str,
    ends_at: str,
    description: str | None = None,
    winner_count: int = 1,
    requirement_role_id: int | None = None,
    message_id: int | None = None,
) -> int:
    """Create a new giveaway entry and return its ID."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            INSERT INTO giveaways (
                guild_id, channel_id, message_id, host_id, prize,
                description, winner_count, requirement_role_id, ends_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """, (
            guild_id, channel_id, message_id, host_id, prize,
            description, winner_count, requirement_role_id, ends_at
        ))
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def set_giveaway_message_id(giveaway_id: int, message_id: int) -> bool:
    """Associate Discord message ID with a giveaway record."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE giveaways SET message_id=? WHERE id=?",
            (message_id, giveaway_id)
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def get_giveaway(giveaway_id: int) -> dict | None:
    """Retrieve giveaway details by primary ID."""
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT * FROM giveaways WHERE id=?", (giveaway_id,)
        )).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_giveaway_by_message(message_id: int) -> dict | None:
    """Retrieve giveaway details by Discord message ID."""
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT * FROM giveaways WHERE message_id=?", (message_id,)
        )).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_active_giveaways(guild_id: int | None = None) -> list[dict]:
    """Retrieve list of active giveaways."""
    db = await get_db()
    try:
        if guild_id:
            rows = await (await db.execute(
                "SELECT * FROM giveaways WHERE status='active' AND guild_id=? ORDER BY ends_at ASC",
                (guild_id,)
            )).fetchall()
        else:
            rows = await (await db.execute(
                "SELECT * FROM giveaways WHERE status='active' ORDER BY ends_at ASC"
            )).fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_recent_giveaways(guild_id: int | None = None, limit: int = 10) -> list[dict]:
    """Retrieve recent giveaways for history display."""
    db = await get_db()
    try:
        if guild_id:
            rows = await (await db.execute(
                "SELECT * FROM giveaways WHERE guild_id=? ORDER BY id DESC LIMIT ?",
                (guild_id, limit)
            )).fetchall()
        else:
            rows = await (await db.execute(
                "SELECT * FROM giveaways ORDER BY id DESC LIMIT ?",
                (limit,)
            )).fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_due_giveaways() -> list[dict]:
    """Retrieve active giveaways whose end timestamp has arrived or passed."""
    db = await get_db()
    try:
        rows = await (await db.execute("""
            SELECT * FROM giveaways
            WHERE status='active' AND (ends_at <= CURRENT_TIMESTAMP OR datetime(ends_at) <= datetime('now'))
            ORDER BY ends_at ASC
        """)).fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def toggle_giveaway_entry(giveaway_id: int, user_id: int) -> tuple[bool, int]:
    """
    Toggle a user's participation in a giveaway.
    Returns (joined: bool, total_entries: int).
    If user was not entered -> joins (returns True, count).
    If user was already entered -> leaves (returns False, count).
    """
    db = await get_db()
    try:
        # Check if already joined
        row = await (await db.execute(
            "SELECT id FROM giveaway_entries WHERE giveaway_id=? AND user_id=?",
            (giveaway_id, user_id)
        )).fetchone()
        if row:
            await db.execute(
                "DELETE FROM giveaway_entries WHERE giveaway_id=? AND user_id=?",
                (giveaway_id, user_id)
            )
            joined = False
        else:
            await db.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
                (giveaway_id, user_id)
            )
            joined = True
        await db.commit()

        count_row = await (await db.execute(
            "SELECT COUNT(*) AS total FROM giveaway_entries WHERE giveaway_id=?",
            (giveaway_id,)
        )).fetchone()
        total_entries = count_row["total"] if count_row else 0
        return (joined, total_entries)
    finally:
        await db.close()


async def is_user_in_giveaway(giveaway_id: int, user_id: int) -> bool:
    """Check if a user is currently registered in a giveaway."""
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT 1 FROM giveaway_entries WHERE giveaway_id=? AND user_id=?",
            (giveaway_id, user_id)
        )).fetchone()
        return bool(row)
    finally:
        await db.close()


async def get_giveaway_entries(giveaway_id: int) -> list[int]:
    """Get list of user IDs registered for a giveaway."""
    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id=? ORDER BY id ASC",
            (giveaway_id,)
        )).fetchall()
        return [row["user_id"] for row in rows]
    finally:
        await db.close()


async def get_giveaway_entry_count(giveaway_id: int) -> int:
    """Get total number of participants for a giveaway."""
    db = await get_db()
    try:
        row = await (await db.execute(
            "SELECT COUNT(*) AS total FROM giveaway_entries WHERE giveaway_id=?",
            (giveaway_id,)
        )).fetchone()
        return row["total"] if row else 0
    finally:
        await db.close()


async def end_giveaway(giveaway_id: int, winner_ids: list[int]) -> bool:
    """Mark a giveaway as ended with the final list of winner IDs."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            UPDATE giveaways
            SET status='ended', ended_at=CURRENT_TIMESTAMP, winners_json=?
            WHERE id=? AND status='active'
        """, (json.dumps(winner_ids), giveaway_id))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def cancel_giveaway(giveaway_id: int) -> bool:
    """Cancel an active giveaway."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            UPDATE giveaways
            SET status='cancelled', ended_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='active'
        """, (giveaway_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


async def update_giveaway_winners(giveaway_id: int, winner_ids: list[int]) -> bool:
    """Update winner list for a giveaway (used during reroll)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE giveaways SET winners_json=? WHERE id=?",
            (json.dumps(winner_ids), giveaway_id)
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


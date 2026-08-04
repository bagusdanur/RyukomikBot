"""Monthly staff performance bonus calculation and invoice integration."""

import json
from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import aiosqlite

from database import DB_PATH

JAKARTA = ZoneInfo("Asia/Jakarta")


async def _db():
    connection = await aiosqlite.connect(DB_PATH, timeout=30)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA busy_timeout=30000")
    await connection.execute("PRAGMA foreign_keys=ON")
    return connection


async def setup_tables(connection=None):
    own = connection is None
    connection = connection or await _db()
    try:
        await connection.executescript("""
            CREATE TABLE IF NOT EXISTS performance_bonus_settings (
                id INTEGER PRIMARY KEY CHECK(id=1),
                quality_weight INTEGER NOT NULL DEFAULT 50,
                speed_weight INTEGER NOT NULL DEFAULT 30,
                consistency_weight INTEGER NOT NULL DEFAULT 20,
                min_chapters INTEGER NOT NULL DEFAULT 3,
                tier_1_score INTEGER NOT NULL DEFAULT 70,
                tier_1_percent INTEGER NOT NULL DEFAULT 4,
                tier_2_score INTEGER NOT NULL DEFAULT 80,
                tier_2_percent INTEGER NOT NULL DEFAULT 6,
                tier_3_score INTEGER NOT NULL DEFAULT 90,
                tier_3_percent INTEGER NOT NULL DEFAULT 10,
                max_amount INTEGER NOT NULL DEFAULT 25000,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT
            );
            INSERT OR IGNORE INTO performance_bonus_settings(id) VALUES(1);
            CREATE TABLE IF NOT EXISTS performance_bonuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id TEXT NOT NULL,
                period TEXT NOT NULL,
                approved_chapters INTEGER NOT NULL,
                eligible_earnings INTEGER NOT NULL,
                revision_chapters INTEGER NOT NULL DEFAULT 0,
                deadline_chapters INTEGER NOT NULL DEFAULT 0,
                on_time_chapters INTEGER NOT NULL DEFAULT 0,
                overdue_chapters INTEGER NOT NULL DEFAULT 0,
                quality_score REAL NOT NULL,
                speed_score REAL,
                consistency_score REAL NOT NULL,
                total_score REAL NOT NULL,
                tier TEXT,
                percentage INTEGER NOT NULL DEFAULT 0,
                proposed_amount INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                reviewed_at DATETIME,
                reviewed_by TEXT,
                rejection_reason TEXT,
                invoice_id INTEGER,
                paid_at DATETIME,
                UNIQUE(staff_id, period)
            );
            CREATE INDEX IF NOT EXISTS idx_performance_bonus_status
                ON performance_bonuses(status,period);
            CREATE TABLE IF NOT EXISTS performance_bonus_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bonus_id INTEGER,
                event_type TEXT NOT NULL,
                actor_id TEXT,
                before_json TEXT,
                after_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS dashboard_invoice_bonus_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                bonus_id INTEGER NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT 'Bonus Performa',
                period TEXT NOT NULL,
                amount INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_invoice_bonus_invoice
                ON dashboard_invoice_bonus_items(invoice_id);
        """)
        # One-time safe rebalance: only replace known untouched defaults.
        # Any configuration already customized by an administrator is preserved.
        await connection.execute("""UPDATE performance_bonus_settings
            SET tier_1_percent=4,tier_2_percent=6,tier_3_percent=10,max_amount=25000,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=1 AND (
                (tier_1_percent=5 AND tier_2_percent=10 AND tier_3_percent=15 AND max_amount=30000)
                OR (tier_1_percent=3 AND tier_2_percent=5 AND tier_3_percent=8 AND max_amount=20000)
            )""")
        if own:
            await connection.commit()
    finally:
        if own:
            await connection.close()


def previous_period(today=None):
    today = today or datetime.now(JAKARTA).date()
    first = today.replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def period_bounds(period):
    year, month = map(int, period.split("-"))
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


async def get_settings(connection=None):
    own = connection is None
    connection = connection or await _db()
    try:
        row = await (await connection.execute(
            "SELECT * FROM performance_bonus_settings WHERE id=1"
        )).fetchone()
        return dict(row)
    finally:
        if own:
            await connection.close()


def validate_settings(values):
    weights = [int(values[k]) for k in ("quality_weight", "speed_weight", "consistency_weight")]
    if sum(weights) != 100 or any(value < 0 for value in weights):
        raise ValueError("Total bobot kualitas, kecepatan, dan konsistensi harus 100%.")
    scores = [int(values[k]) for k in ("tier_1_score", "tier_2_score", "tier_3_score")]
    percents = [int(values[k]) for k in ("tier_1_percent", "tier_2_percent", "tier_3_percent")]
    if not (0 <= scores[0] < scores[1] < scores[2] <= 100):
        raise ValueError("Batas skor tier harus berurutan dan maksimal 100.")
    if not (0 <= percents[0] <= percents[1] <= percents[2] <= 100):
        raise ValueError("Persentase tier harus berurutan.")
    if int(values["min_chapters"]) < 1 or int(values["max_amount"]) < 0:
        raise ValueError("Minimal chapter dan batas bonus tidak valid.")


async def update_settings(values, actor_id):
    validate_settings(values)
    connection = await _db()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        before = await get_settings(connection)
        columns = ("quality_weight", "speed_weight", "consistency_weight", "min_chapters",
                   "tier_1_score", "tier_1_percent", "tier_2_score", "tier_2_percent",
                   "tier_3_score", "tier_3_percent", "max_amount")
        await connection.execute(f"""UPDATE performance_bonus_settings SET
            {','.join(f'{key}=?' for key in columns)},updated_at=CURRENT_TIMESTAMP,updated_by=? WHERE id=1""",
            [*[int(values[key]) for key in columns], str(actor_id)])
        after = await get_settings(connection)
        await connection.execute("""INSERT INTO performance_bonus_events
            (event_type,actor_id,before_json,after_json) VALUES('settings_updated',?,?,?)""",
            (str(actor_id), json.dumps(before), json.dumps(after)))
        await connection.commit()
        return after
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()


def _tier(score, settings):
    if score >= settings["tier_3_score"]:
        return "Istimewa", settings["tier_3_percent"]
    if score >= settings["tier_2_score"]:
        return "Sangat Baik", settings["tier_2_percent"]
    if score >= settings["tier_1_score"]:
        return "Baik", settings["tier_1_percent"]
    return None, 0


async def _revision_count(connection, assignment):
    count = int((await (await connection.execute("""SELECT COUNT(*) total FROM assignment_events
        WHERE assignment_id=? AND event_type IN ('revision','revised','revision_requested')""",
        (assignment["id"],))).fetchone())["total"])
    if assignment["pair_chapter_id"]:
        targets = ("revision_tl", "revision_both") if assignment["role"] == "TL" else ("revision_ts", "revision_both")
        pair_count = int((await (await connection.execute("""SELECT COUNT(*) total FROM pair_events
            WHERE chapter_id=? AND event_type IN (?,?)""",
            (assignment["pair_chapter_id"], *targets))).fetchone())["total"])
        count += pair_count
    return count


async def calculate_staff(connection, staff_id, period, settings):
    start, end = period_bounds(period)
    assignments = await (await connection.execute("""SELECT * FROM assignments
        WHERE CAST(staff_id AS TEXT)=? AND status IN ('approved','paid')
          AND date(approved_at) BETWEEN ? AND ? ORDER BY id""",
        (str(staff_id), str(start), str(end)))).fetchall()
    approved = sum(int(row["chapter_count"] or 1) for row in assignments)
    earnings = sum(int(row["final_rate"] or 0) for row in assignments)
    revisions = deadline_chapters = on_time = 0
    evidence = []
    for row in assignments:
        chapters = int(row["chapter_count"] or 1)
        revision_count = await _revision_count(connection, row)
        if revision_count:
            revisions += chapters
        deadline = row["deadline_at"]
        timely = None
        if deadline:
            deadline_chapters += chapters
            timely = str(row["approved_at"] or "")[:10] <= str(deadline)[:10]
            if timely:
                on_time += chapters
        evidence.append({"assignment_id": row["id"], "manga": row["manga"], "chapter": row["chapter"],
                         "role": row["role"], "chapters": chapters, "amount": row["final_rate"],
                         "deadline": deadline, "approved_at": row["approved_at"],
                         "revision_count": revision_count, "on_time": timely})
    overdue = int((await (await connection.execute("""SELECT COALESCE(SUM(chapter_count),0) total
        FROM assignments WHERE CAST(staff_id AS TEXT)=? AND status NOT IN ('approved','paid','cancelled')
          AND deadline_at IS NOT NULL AND date(deadline_at) BETWEEN ? AND ? AND date(deadline_at) < date('now')""",
        (str(staff_id), str(start), str(end)))).fetchone())["total"])
    quality = (max(0, approved - revisions) / approved * 100) if approved else 0
    speed = (on_time / deadline_chapters * 100) if deadline_chapters else None
    consistency = (approved / (approved + overdue) * 100) if approved + overdue else 0
    if speed is None:
        denominator = settings["quality_weight"] + settings["consistency_weight"]
        score = ((quality * settings["quality_weight"] + consistency * settings["consistency_weight"])
                 / denominator) if denominator else 0
    else:
        score = (quality * settings["quality_weight"] + speed * settings["speed_weight"]
                 + consistency * settings["consistency_weight"]) / 100
    score = round(min(100, max(0, score)), 2)
    tier, percentage = _tier(score, settings)
    eligible = approved >= settings["min_chapters"] and tier is not None
    amount = min(settings["max_amount"], round(earnings * percentage / 100)) if eligible else 0
    return {"staff_id": str(staff_id), "period": period, "approved_chapters": approved,
            "eligible_earnings": earnings, "revision_chapters": revisions,
            "deadline_chapters": deadline_chapters, "on_time_chapters": on_time,
            "overdue_chapters": overdue, "quality_score": round(quality, 2),
            "speed_score": round(speed, 2) if speed is not None else None,
            "consistency_score": round(consistency, 2), "total_score": score,
            "tier": tier, "percentage": percentage, "proposed_amount": amount,
            "status": "pending" if eligible else "ineligible",
            "metrics_json": json.dumps({"assignments": evidence, "no_deadline_redistribution": speed is None})}


async def evaluate_period(period=None):
    period = period or previous_period()
    period_bounds(period)
    connection = await _db()
    generated = []
    try:
        await connection.execute("BEGIN IMMEDIATE")
        settings = await get_settings(connection)
        start, end = period_bounds(period)
        staff_rows = await (await connection.execute("""SELECT DISTINCT CAST(staff_id AS TEXT) staff_id
            FROM assignments WHERE staff_id IS NOT NULL AND status IN ('approved','paid')
              AND date(approved_at) BETWEEN ? AND ?""", (str(start), str(end)))).fetchall()
        for staff in staff_rows:
            result = await calculate_staff(connection, staff["staff_id"], period, settings)
            existing = await (await connection.execute("""SELECT id,status FROM performance_bonuses
                WHERE staff_id=? AND period=?""", (result["staff_id"], period))).fetchone()
            columns = tuple(key for key in result if key not in {"staff_id", "period"})
            if not existing:
                cursor = await connection.execute(f"""INSERT INTO performance_bonuses
                    (staff_id,period,{','.join(columns)}) VALUES(?,?,{','.join('?' for _ in columns)})""",
                    [result["staff_id"], period, *[result[key] for key in columns]])
                result["id"] = cursor.lastrowid
                generated.append(result)
            elif existing["status"] in {"pending", "ineligible"}:
                await connection.execute(f"""UPDATE performance_bonuses SET
                    {','.join(f'{key}=?' for key in columns)},generated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    [*[result[key] for key in columns], existing["id"]])
                result["id"] = existing["id"]
                generated.append(result)
        await connection.commit()
        return generated
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()


async def list_bonuses(period=None, status=None):
    connection = await _db()
    try:
        clauses, params = [], []
        if period:
            clauses.append("period=?"); params.append(period)
        if status:
            clauses.append("status=?"); params.append(status)
        rows = await (await connection.execute(f"""SELECT * FROM performance_bonuses
            {'WHERE ' + ' AND '.join(clauses) if clauses else ''}
            ORDER BY period DESC,total_score DESC,staff_id""", params)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metrics"] = json.loads(item.pop("metrics_json") or "{}")
            result.append(item)
        return result
    finally:
        await connection.close()


async def review_bonus(bonus_id, action, actor_id, reason=None):
    if action not in {"approve", "reject"}:
        raise ValueError("Aksi bonus tidak valid.")
    if action == "reject" and not str(reason or "").strip():
        raise ValueError("Alasan penolakan wajib diisi.")
    connection = await _db()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        row = await (await connection.execute(
            "SELECT * FROM performance_bonuses WHERE id=?", (bonus_id,))).fetchone()
        if not row or row["status"] != "pending":
            raise ValueError("Bonus tidak ditemukan atau sudah diproses.")
        status = "approved" if action == "approve" else "rejected"
        await connection.execute("""UPDATE performance_bonuses SET status=?,reviewed_at=CURRENT_TIMESTAMP,
            reviewed_by=?,rejection_reason=? WHERE id=?""",
            (status, str(actor_id), str(reason).strip() if reason else None, bonus_id))
        after = dict(row); after["status"] = status
        await connection.execute("""INSERT INTO performance_bonus_events
            (bonus_id,event_type,actor_id,before_json,after_json) VALUES(?,?,?,?,?)""",
            (bonus_id, status, str(actor_id), json.dumps(dict(row)), json.dumps(after)))
        await connection.commit()
        result = dict(row)
        result.update(status=status, reviewed_by=str(actor_id), rejection_reason=str(reason).strip() if reason else None)
        result["metrics"] = json.loads(result.pop("metrics_json") or "{}")
        return result
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()


async def attach_approved_to_invoice(connection, invoice_id, staff_id):
    rows = await (await connection.execute("""SELECT * FROM performance_bonuses
        WHERE staff_id=? AND status='approved' AND invoice_id IS NULL AND proposed_amount>0
        ORDER BY period,id""", (str(staff_id),))).fetchall()
    for row in rows:
        await connection.execute("""INSERT OR IGNORE INTO dashboard_invoice_bonus_items
            (invoice_id,bonus_id,description,period,amount) VALUES(?,?,'Bonus Performa',?,?)""",
            (invoice_id, row["id"], row["period"], row["proposed_amount"]))
        await connection.execute("""UPDATE performance_bonuses SET status='invoiced',invoice_id=?
            WHERE id=? AND status='approved' AND invoice_id IS NULL""", (invoice_id, row["id"]))
    return sum(int(row["proposed_amount"]) for row in rows)


async def invoice_bonus_items(connection, invoice_id):
    rows = await (await connection.execute("""SELECT b.*,p.total_score,p.percentage
        FROM dashboard_invoice_bonus_items b JOIN performance_bonuses p ON p.id=b.bonus_id
        WHERE b.invoice_id=? ORDER BY b.id""", (invoice_id,))).fetchall()
    return [dict(row) for row in rows]


async def mark_invoice_paid(connection, invoice_id):
    await connection.execute("""UPDATE performance_bonuses SET status='paid',paid_at=CURRENT_TIMESTAMP
        WHERE invoice_id=? AND status='invoiced'""", (invoice_id,))


async def release_invoice(connection, invoice_id):
    await connection.execute("""UPDATE performance_bonuses SET status='approved',invoice_id=NULL
        WHERE invoice_id=? AND status='invoiced'""", (invoice_id,))
    await connection.execute("DELETE FROM dashboard_invoice_bonus_items WHERE invoice_id=?", (invoice_id,))

"""Transactional TL/TS collaboration workflow, one payable unit per chapter."""

import json
from datetime import datetime
from typing import Any, Optional

import database as db_module
from raw_downloader.resolver import normalize_title


PAIR_ACTIVE_STATES = {
    "waiting_tl", "ready_for_ts", "tl_revision", "ts_revision",
    "both_revision", "final_review",
}


async def setup_pair_tables() -> None:
    db = await db_module.get_db()
    try:
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(assignments)")).fetchall()}
        if "pair_project_id" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN pair_project_id INTEGER")
        if "pair_chapter_id" not in columns:
            await db.execute("ALTER TABLE assignments ADD COLUMN pair_chapter_id INTEGER")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pair_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                manga TEXT NOT NULL,
                chapters TEXT NOT NULL,
                tl_staff_id INTEGER NOT NULL,
                ts_staff_id INTEGER NOT NULL,
                tl_rate_per_chapter INTEGER NOT NULL,
                ts_rate_per_chapter INTEGER NOT NULL,
                deadline_at DATETIME,
                status TEXT NOT NULL DEFAULT 'active',
                channel_id INTEGER,
                panel_message_id INTEGER,
                created_by TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pair_chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                chapter TEXT NOT NULL,
                tl_assignment_id INTEGER NOT NULL UNIQUE,
                ts_assignment_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'waiting_tl',
                tl_link TEXT,
                final_link TEXT,
                notes TEXT,
                review_message_id INTEGER,
                tl_submitted_at DATETIME,
                final_submitted_at DATETIME,
                approved_at DATETIME,
                approved_by TEXT,
                UNIQUE(project_id, chapter),
                FOREIGN KEY(project_id) REFERENCES pair_projects(id),
                FOREIGN KEY(tl_assignment_id) REFERENCES assignments(id),
                FOREIGN KEY(ts_assignment_id) REFERENCES assignments(id)
            )
        """)
        chapter_columns = {
            row[1] for row in await (await db.execute("PRAGMA table_info(pair_chapters)")).fetchall()
        }
        if "ts_handoff_message_id" not in chapter_columns:
            await db.execute("ALTER TABLE pair_chapters ADD COLUMN ts_handoff_message_id INTEGER")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pair_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                chapter_id INTEGER,
                event_type TEXT NOT NULL,
                actor_id TEXT,
                detail TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES pair_projects(id),
                FOREIGN KEY(chapter_id) REFERENCES pair_chapters(id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_pair_chapters_project_status ON pair_chapters(project_id,status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_assignments_pair_project ON assignments(pair_project_id,pair_chapter_id)")
        await db.commit()
    finally:
        await db.close()


async def create_project(
    *, manga: str, chapters: list[str], tl_staff_id: int, ts_staff_id: int,
    tl_rate_per_chapter: int, ts_rate_per_chapter: int,
    deadline_at: Optional[str], created_by: Optional[int],
) -> dict[str, Any]:
    """Create one project and two non-payable assignments for every chapter."""
    db = await db_module.get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            """INSERT INTO pair_projects
               (manga,chapters,tl_staff_id,ts_staff_id,tl_rate_per_chapter,
                ts_rate_per_chapter,deadline_at,created_by)
               VALUES(?,?,?,?,?,?,?,?)""",
            (manga, json.dumps(chapters, ensure_ascii=False), tl_staff_id, ts_staff_id,
             tl_rate_per_chapter, ts_rate_per_chapter, deadline_at,
             str(created_by) if created_by else None),
        )
        project_id = int(cursor.lastrowid)
        chapter_rows = []
        for chapter in chapters:
            tl_cursor = await db.execute(
                """INSERT INTO assignments
                   (manga,chapter,staff_id,role,base_rate,final_rate,multiplier,status,
                    claimed_at,deadline_at,chapters,chapter_count,rate_per_chapter,pair_project_id)
                   VALUES(?,?,?,?,?,?,1.0,'pair_waiting',CURRENT_TIMESTAMP,?,?,1,?,?)""",
                (manga, chapter, tl_staff_id, "TL", tl_rate_per_chapter,
                 tl_rate_per_chapter, deadline_at, json.dumps([chapter], ensure_ascii=False),
                 tl_rate_per_chapter, project_id),
            )
            ts_cursor = await db.execute(
                """INSERT INTO assignments
                   (manga,chapter,staff_id,role,base_rate,final_rate,multiplier,status,
                    claimed_at,deadline_at,chapters,chapter_count,rate_per_chapter,pair_project_id)
                   VALUES(?,?,?,?,?,?,1.0,'pair_waiting',CURRENT_TIMESTAMP,?,?,1,?,?)""",
                (manga, chapter, ts_staff_id, "TS", ts_rate_per_chapter,
                 ts_rate_per_chapter, deadline_at, json.dumps([chapter], ensure_ascii=False),
                 ts_rate_per_chapter, project_id),
            )
            chapter_cursor = await db.execute(
                """INSERT INTO pair_chapters(project_id,chapter,tl_assignment_id,ts_assignment_id)
                   VALUES(?,?,?,?)""",
                (project_id, chapter, int(tl_cursor.lastrowid), int(ts_cursor.lastrowid)),
            )
            chapter_id = int(chapter_cursor.lastrowid)
            await db.execute(
                "UPDATE assignments SET pair_chapter_id=? WHERE id IN (?,?)",
                (chapter_id, int(tl_cursor.lastrowid), int(ts_cursor.lastrowid)),
            )
            chapter_rows.append({"id": chapter_id, "chapter": chapter})
        await db.execute(
            "INSERT INTO pair_events(project_id,event_type,actor_id,detail) VALUES(?,?,?,?)",
            (project_id, "created", str(created_by) if created_by else None,
             f"Pair dibuat untuk {len(chapters)} chapter."),
        )
        await db.commit()
        return {"id": project_id, "chapters": chapter_rows}
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def set_workspace(project_id: int, channel_id: int, panel_message_id: int) -> None:
    db = await db_module.get_db()
    try:
        await db.execute(
            "UPDATE pair_projects SET channel_id=?,panel_message_id=? WHERE id=?",
            (channel_id, panel_message_id, project_id),
        )
        await db.commit()
    finally:
        await db.close()


async def find_reusable_workspace(manga: str) -> Optional[dict[str, Any]]:
    """Return the permanent Discord workspace for this manga title."""
    db = await db_module.get_db()
    try:
        rows = await (await db.execute(
            """SELECT id,channel_id,panel_message_id,manga,completed_at
               FROM pair_projects
               WHERE channel_id IS NOT NULL
               ORDER BY id DESC""",
        )).fetchall()
        wanted = normalize_title(manga)
        row = next((entry for entry in rows if normalize_title(entry["manga"]) == wanted), None)
        return dict(row) if row else None
    finally:
        await db.close()


async def record_workspace_reuse(project_id: int, previous_project_id: int) -> None:
    db = await db_module.get_db()
    try:
        await db.execute(
            "INSERT INTO pair_events(project_id,event_type,detail) VALUES(?,?,?)",
            (project_id, "workspace_reused", f"Channel digunakan ulang dari Pair Project #{previous_project_id}."),
        )
        await db.commit()
    finally:
        await db.close()


async def delete_unpublished_project(project_id: int) -> None:
    """Rollback a newly-created project when Discord workspace creation fails."""
    db = await db_module.get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        project = await (await db.execute(
            "SELECT channel_id FROM pair_projects WHERE id=?", (project_id,)
        )).fetchone()
        if not project or project["channel_id"]:
            await db.rollback()
            return
        await db.execute("DELETE FROM pair_events WHERE project_id=?", (project_id,))
        await db.execute("DELETE FROM pair_chapters WHERE project_id=?", (project_id,))
        await db.execute("DELETE FROM assignments WHERE pair_project_id=? AND status='pair_waiting'", (project_id,))
        await db.execute("DELETE FROM pair_projects WHERE id=?", (project_id,))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def get_project(project_id: int) -> Optional[dict[str, Any]]:
    db = await db_module.get_db()
    try:
        project = await (await db.execute("SELECT * FROM pair_projects WHERE id=?", (project_id,))).fetchone()
        if not project:
            return None
        chapters = await (await db.execute(
            "SELECT * FROM pair_chapters WHERE project_id=? ORDER BY id", (project_id,)
        )).fetchall()
        result = dict(project)
        result["chapters"] = [dict(row) for row in chapters]
        return result
    finally:
        await db.close()


async def get_chapter(chapter_id: int) -> Optional[dict[str, Any]]:
    db = await db_module.get_db()
    try:
        row = await (await db.execute(
            """SELECT c.*,p.manga,p.tl_staff_id,p.ts_staff_id,p.tl_rate_per_chapter,
                      p.ts_rate_per_chapter,p.channel_id,p.panel_message_id,p.deadline_at
               FROM pair_chapters c JOIN pair_projects p ON p.id=c.project_id WHERE c.id=?""",
            (chapter_id,),
        )).fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def set_ts_handoff_message(chapter_id: int, message_id: Optional[int]) -> None:
    db = await db_module.get_db()
    try:
        await db.execute(
            "UPDATE pair_chapters SET ts_handoff_message_id=? WHERE id=?",
            (message_id, chapter_id),
        )
        await db.commit()
    finally:
        await db.close()


async def list_projects(staff_id: Optional[int] = None) -> list[dict[str, Any]]:
    db = await db_module.get_db()
    try:
        where, params = "", []
        if staff_id is not None:
            where, params = "WHERE p.tl_staff_id=? OR p.ts_staff_id=?", [staff_id, staff_id]
        projects = await (await db.execute(
            f"SELECT p.* FROM pair_projects p {where} ORDER BY p.created_at DESC", params
        )).fetchall()
        results = []
        for project in projects:
            item = dict(project)
            rows = await (await db.execute(
                "SELECT * FROM pair_chapters WHERE project_id=? ORDER BY id", (item["id"],)
            )).fetchall()
            item["chapters"] = [dict(row) for row in rows]
            results.append(item)
        return results
    finally:
        await db.close()


async def _event(db, chapter: dict, event_type: str, actor_id: int, detail: str) -> None:
    await db.execute(
        "INSERT INTO pair_events(project_id,chapter_id,event_type,actor_id,detail) VALUES(?,?,?,?,?)",
        (chapter["project_id"], chapter["id"], event_type, str(actor_id), detail),
    )


async def submit_tl(chapter_id: int, actor_id: int, link: str, notes: Optional[str]) -> bool:
    db = await db_module.get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute(
            """SELECT c.*,p.tl_staff_id FROM pair_chapters c JOIN pair_projects p ON p.id=c.project_id
               WHERE c.id=?""", (chapter_id,)
        )).fetchone()
        if not row or int(row["tl_staff_id"]) != actor_id or row["status"] not in {"waiting_tl", "tl_revision", "both_revision"}:
            await db.rollback()
            return False
        chapter = dict(row)
        await db.execute(
            """UPDATE pair_chapters SET status='ready_for_ts',tl_link=?,notes=?,tl_submitted_at=CURRENT_TIMESTAMP
               WHERE id=?""", (link, notes, chapter_id),
        )
        await db.execute(
            "UPDATE assignments SET gdrive_link=?,submitted_at=CURRENT_TIMESTAMP,admin_notes=? WHERE id=?",
            (link, notes, chapter["tl_assignment_id"]),
        )
        await _event(db, chapter, "tl_submitted", actor_id, notes or "Hasil TL dikirim.")
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def submit_final(chapter_id: int, actor_id: int, link: str, notes: Optional[str]) -> bool:
    db = await db_module.get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute(
            """SELECT c.*,p.ts_staff_id FROM pair_chapters c JOIN pair_projects p ON p.id=c.project_id
               WHERE c.id=?""", (chapter_id,)
        )).fetchone()
        if not row or int(row["ts_staff_id"]) != actor_id or row["status"] not in {"ready_for_ts", "ts_revision"}:
            await db.rollback()
            return False
        chapter = dict(row)
        await db.execute(
            """UPDATE pair_chapters SET status='final_review',final_link=?,notes=?,final_submitted_at=CURRENT_TIMESTAMP
               WHERE id=?""", (link, notes, chapter_id),
        )
        await db.execute(
            "UPDATE assignments SET gdrive_link=?,submitted_at=CURRENT_TIMESTAMP,admin_notes=? WHERE id=?",
            (link, notes, chapter["ts_assignment_id"]),
        )
        await _event(db, chapter, "final_submitted", actor_id, notes or "Hasil final dikirim.")
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def request_revision(chapter_id: int, actor_id: int, target: str, notes: str, *, admin: bool = False) -> bool:
    if target not in {"tl", "ts", "both"}:
        return False
    db = await db_module.get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute(
            """SELECT c.*,p.ts_staff_id FROM pair_chapters c JOIN pair_projects p ON p.id=c.project_id
               WHERE c.id=?""", (chapter_id,)
        )).fetchone()
        if not row or (not admin and (target != "tl" or int(row["ts_staff_id"]) != actor_id)):
            await db.rollback()
            return False
        allowed = {"ready_for_ts", "ts_revision", "final_review"} if target == "tl" else {"final_review"}
        if row["status"] not in allowed:
            await db.rollback()
            return False
        chapter = dict(row)
        state = {"tl": "tl_revision", "ts": "ts_revision", "both": "both_revision"}[target]
        await db.execute("UPDATE pair_chapters SET status=?,notes=? WHERE id=?", (state, notes, chapter_id))
        await _event(db, chapter, f"revision_{target}", actor_id, notes)
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def approve_final(chapter_id: int, actor_id: int) -> Optional[dict[str, Any]]:
    """Release both salaries atomically only from final_review."""
    db = await db_module.get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute(
            "SELECT * FROM pair_chapters WHERE id=?", (chapter_id,)
        )).fetchone()
        if not row or row["status"] != "final_review":
            await db.rollback()
            return None
        chapter = dict(row)
        now = datetime.now().isoformat(timespec="seconds")
        cursor = await db.execute(
            """UPDATE assignments SET status='approved',approved_at=?
               WHERE id IN (?,?) AND status='pair_waiting'""",
            (now, chapter["tl_assignment_id"], chapter["ts_assignment_id"]),
        )
        if cursor.rowcount != 2:
            await db.rollback()
            return None
        await db.execute(
            """UPDATE pair_chapters SET status='completed',approved_at=?,approved_by=? WHERE id=?""",
            (now, str(actor_id), chapter_id),
        )
        remaining = (await (await db.execute(
            "SELECT COUNT(*) FROM pair_chapters WHERE project_id=? AND id<>? AND status<>'completed'",
            (chapter["project_id"], chapter_id),
        )).fetchone())[0]
        if not remaining:
            await db.execute(
                "UPDATE pair_projects SET status='completed',completed_at=? WHERE id=?",
                (now, chapter["project_id"]),
            )
        await _event(db, chapter, "approved_final", actor_id, "Gaji TL dan TS dilepas bersamaan.")
        await db.commit()
        return await get_chapter(chapter_id)
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def set_review_message(chapter_id: int, message_id: Optional[int]) -> None:
    db = await db_module.get_db()
    try:
        await db.execute("UPDATE pair_chapters SET review_message_id=? WHERE id=?", (message_id, chapter_id))
        await db.commit()
    finally:
        await db.close()


async def timeline(project_id: int) -> list[dict[str, Any]]:
    db = await db_module.get_db()
    try:
        rows = await (await db.execute(
            "SELECT * FROM pair_events WHERE project_id=? ORDER BY created_at DESC,id DESC", (project_id,)
        )).fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()

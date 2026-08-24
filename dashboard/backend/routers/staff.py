"""Staff router — Staff directory listing and sync."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from dashboard.backend.deps import admin_user, current_user, audit, dashboard_db, _staff_cache
from dashboard.backend.helpers import enrich_staff, staff_directory
from dashboard.backend.helpers import discord_api
from dashboard.backend.deps import normalize_paging, page_payload
from config import GUILD_ID, REKRUT_CAT_ID, ROLE_STAFF_ID

router = APIRouter(prefix="/api", tags=["staff"])


class StaffQuestionCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=2, max_length=1800)
    requires_answer: bool = True


class StaffQuestionAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=1800)


@router.get("/staff/questions")
async def staff_questions(user=Depends(current_user)):
    connection = await dashboard_db()
    try:
        questions = await (await connection.execute(
            "SELECT * FROM staff_questions ORDER BY id DESC LIMIT 100"
        )).fetchall()
        result = []
        for question in questions:
            item = dict(question)
            if user["role"] == "admin":
                rows = await (await connection.execute(
                    "SELECT CAST(staff_id AS TEXT) staff_id,answer,created_at,updated_at "
                    "FROM staff_question_responses WHERE question_id=? ORDER BY updated_at DESC",
                    (question["id"],),
                )).fetchall()
                item["responses"] = [dict(row) for row in rows]
            else:
                row = await (await connection.execute(
                    "SELECT answer,created_at,updated_at FROM staff_question_responses "
                    "WHERE question_id=? AND staff_id=?",
                    (question["id"], int(user["id"])),
                )).fetchone()
                item["my_response"] = dict(row) if row else None
            result.append(item)
        return result
    finally:
        await connection.close()


@router.post("/staff/questions")
async def create_staff_question(payload: StaffQuestionCreate, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        cursor = await connection.execute(
            "INSERT INTO staff_questions(title,message,created_by,requires_answer) VALUES(?,?,?,?)",
            (payload.title.strip(), payload.message.strip(), int(user["id"]), int(payload.requires_answer)),
        )
        await connection.commit()
        question_id = int(cursor.lastrowid)
    finally:
        await connection.close()
    channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels") or []
    directory = await staff_directory()
    sent, failed = 0, 0
    for profile in directory:
        staff_id = str(profile["id"])
        ticket = next((channel for channel in channels if channel.get("type") == 0
            and str(channel.get("parent_id")) == str(REKRUT_CAT_ID)
            and staff_id in str(channel.get("topic") or "")), None)
        if not ticket:
            failed += 1
            continue
        components = []
        if payload.requires_answer:
            components = [{"type": 1, "components": [{
                "type": 2, "style": 1, "label": "Jawab Pertanyaan",
                "custom_id": f"staff_question:answer:{question_id}:v1",
            }]}]
        result = await discord_api("POST", f"/channels/{ticket['id']}/messages", {
            "content": f"<@{staff_id}>",
            "embeds": [{
                "title": ("❓ " if payload.requires_answer else "📢 ") + payload.title.strip(),
                "description": payload.message.strip(),
                "color": 5793266,
                "footer": {"text": f"Pesan Staff #{question_id} • Dari Administrator"},
            }],
            "components": components,
            "allowed_mentions": {"parse": [], "users": [staff_id]},
        })
        if result: sent += 1
        else: failed += 1
    await audit(user["id"], "staff.question.create", "staff_question", question_id, None, {**payload.model_dump(), "sent": sent, "failed": failed})
    return {"ok": failed == 0, "id": question_id, "sent": sent, "failed": failed}


@router.put("/staff/questions/{question_id}/answer")
async def answer_staff_question(question_id: int, payload: StaffQuestionAnswer, user=Depends(current_user)):
    connection = await dashboard_db()
    try:
        question = await (await connection.execute(
            "SELECT status FROM staff_questions WHERE id=?", (question_id,)
        )).fetchone()
        if not question:
            raise HTTPException(404, "Pertanyaan tidak ditemukan.")
        if question["status"] != "open":
            raise HTTPException(409, "Pertanyaan ini sudah ditutup.")
        await connection.execute(
            """INSERT INTO staff_question_responses(question_id,staff_id,answer)
               VALUES(?,?,?) ON CONFLICT(question_id,staff_id) DO UPDATE SET
               answer=excluded.answer,updated_at=CURRENT_TIMESTAMP""",
            (question_id, int(user["id"]), payload.answer.strip()),
        )
        await connection.commit()
    finally:
        await connection.close()
    return {"ok": True}


@router.post("/staff/questions/{question_id}/close")
async def close_staff_question(question_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        cursor = await connection.execute(
            "UPDATE staff_questions SET status='closed',closed_at=CURRENT_TIMESTAMP WHERE id=? AND status='open'",
            (question_id,),
        )
        await connection.commit()
        if not cursor.rowcount:
            raise HTTPException(404, "Pertanyaan aktif tidak ditemukan.")
    finally:
        await connection.close()
    await audit(user["id"], "staff.question.close", "staff_question", question_id)
    return {"ok": True}


@router.post("/staff/sync")
async def sync_staff_cache(user=Depends(admin_user)):
    rows = await staff_directory(force=True)
    await audit(user["id"], "staff.sync", "discord_cache", after={"count": len(rows)})
    return {"ok": True, "count": len(rows), "updated_at": _staff_cache["updated_at"]}


@router.get("/staff")
async def staff(
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    paginated: bool = Query(default=False), _user=Depends(admin_user),
):
    page, page_size, paginated = normalize_paging(page, page_size, paginated)
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute("""
            SELECT CAST(staff_id AS TEXT) staff_id,
                   COUNT(*) task_count,
                   SUM(CASE WHEN status IN ('claimed','submitted','revision','pair_waiting') THEN 1 ELSE 0 END) active_count,
                   SUM(CASE WHEN status='approved' THEN final_rate ELSE 0 END) approved_amount,
                   SUM(CASE WHEN status='paid' THEN final_rate ELSE 0 END) paid_amount
            FROM assignments WHERE staff_id IS NOT NULL GROUP BY staff_id ORDER BY task_count DESC
        """)).fetchall()
        stats = {str(row["staff_id"]): dict(row) for row in rows}
    finally:
        await connection.close()
    directory = await staff_directory()
    result = []
    for profile in directory:
        staff_id = str(profile["id"])
        s_stats = stats.get(staff_id, {"task_count": 0, "active_count": 0, "approved_amount": 0, "paid_amount": 0})
        result.append({
            **profile,
            **s_stats,
            "id": staff_id,
            "staff_id": staff_id,
        })
    if paginated:
        start = (page - 1) * page_size
        return page_payload(result[start:start + page_size], page, page_size, len(result))
    return result


@router.get("/staff/workload")
async def staff_workload(_user=Depends(admin_user)):
    """Detailed workload per staff — active tasks, deadlines, overdue."""
    connection = await dashboard_db()
    try:
        # Task counts per staff per status
        rows = await (await connection.execute("""
            SELECT staff_id, status, COUNT(*) as cnt
            FROM assignments
            WHERE staff_id IS NOT NULL AND status IN ('open','claimed','submitted','revision','approved')
            GROUP BY staff_id, status
        """)).fetchall()
        by_staff: dict = {}
        for row in rows:
            sid = str(row["staff_id"])
            by_staff.setdefault(sid, {})[row["status"]] = row["cnt"]

        # Upcoming deadlines (next 7 days)
        deadlines = await (await connection.execute("""
            SELECT staff_id, manga, chapter, deadline_at, status
            FROM assignments
            WHERE staff_id IS NOT NULL
              AND deadline_at IS NOT NULL
              AND status IN ('claimed','submitted','revision')
              AND deadline_at <= date('now', '+7 days')
              AND deadline_at >= date('now', '-1 day')
            ORDER BY deadline_at ASC
            LIMIT 50
        """)).fetchall()

        # Overdue
        overdue = await (await connection.execute("""
            SELECT staff_id, manga, chapter, deadline_at, status
            FROM assignments
            WHERE staff_id IS NOT NULL
              AND deadline_at IS NOT NULL
              AND status IN ('claimed','submitted','revision')
              AND deadline_at < date('now')
            ORDER BY deadline_at ASC
            LIMIT 20
        """)).fetchall()
    finally:
        await connection.close()

    directory = await staff_directory()
    profiles = {p["id"]: p for p in directory}

    workload = []
    for staff_id, counts in by_staff.items():
        profile = profiles.get(staff_id, {"id": staff_id, "username": f"Staff {staff_id}", "avatar": None})
        total_active = sum(counts.values())
        workload.append({
            "staff_id": staff_id,
            "username": profile.get("username"),
            "avatar": profile.get("avatar"),
            "total_active": total_active,
            "by_status": counts,
            "load_level": "overload" if total_active >= 8 else "busy" if total_active >= 4 else "normal" if total_active >= 1 else "idle",
        })
    workload.sort(key=lambda x: x["total_active"], reverse=True)

    deadline_list = []
    for row in deadlines:
        p = profiles.get(str(row["staff_id"]), {})
        deadline_list.append({
            "staff_id": str(row["staff_id"]),
            "staff_name": p.get("username", f"Staff {row['staff_id']}"),
            "manga": row["manga"],
            "chapter": row["chapter"],
            "deadline_at": row["deadline_at"],
            "status": row["status"],
        })

    overdue_list = []
    for row in overdue:
        p = profiles.get(str(row["staff_id"]), {})
        overdue_list.append({
            "staff_id": str(row["staff_id"]),
            "staff_name": p.get("username", f"Staff {row['staff_id']}"),
            "manga": row["manga"],
            "chapter": row["chapter"],
            "deadline_at": row["deadline_at"],
            "status": row["status"],
        })

    return {
        "workload": workload,
        "upcoming_deadlines": deadline_list,
        "overdue": overdue_list,
        "summary": {
            "total_staff": len(workload),
            "overload": sum(1 for w in workload if w["load_level"] == "overload"),
            "busy": sum(1 for w in workload if w["load_level"] == "busy"),
            "normal": sum(1 for w in workload if w["load_level"] == "normal"),
            "idle": sum(1 for w in workload if w["load_level"] == "idle"),
            "overdue_count": len(overdue_list),
        },
    }

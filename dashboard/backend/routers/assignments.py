"""Assignments router — CRUD, approve, revision, timeline, TL-TS pair.

Endpoints moved from app.py:
  GET    /api/assignments                          → list assignments
  GET    /api/assignments/{id}/timeline            → assignment timeline
  POST   /api/assignments                          → create assignment
  POST   /api/assignments/tl-ts-pair               → create TL-TS pair project
  PUT    /api/assignments/{id}                     → update assignment
  POST   /api/assignments/{id}/approve             → approve submitted assignment
  POST   /api/assignments/{id}/revision            → request revision

Pydantic models moved: AssignmentCreate, TlTsPairCreate, AssignmentUpdate, RevisionRequest.
Helpers moved: resolve_staff_ticket_channel, send_assignment_notice,
               send_assignment_update_notice, send_ticket_review_notice.
"""

import asyncio
import hashlib
import json
from datetime import date, datetime
from io import BytesIO
from typing import Literal

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

import database as staff_db
import operations
import pair_workflow as pair_service
from chapter_utils import chapter_display, parse_chapters
from config import GUILD_ID, STAFF_TASKS_CHANNEL_ID, TOKEN

from dashboard.backend.deps import (
    DEFAULT_RATE_RANGES,
    DEV_BYPASS,
    _staff_cache,
    _staff_cache_lock,
    admin_user,
    audit,
    current_user,
    dashboard_db,
    normalize_paging,
    page_payload,
)

# Shared helpers
from dashboard.backend.helpers import (
    create_pair_workspace,
    discord_api,
    enrich_staff,
    resolve_staff_id_with_fallback,
    role_rate_range,
    staff_directory,
)
from enums import AssignmentStatus, EventType

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


def require_current_deadline(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="Format deadline harus YYYY-MM-DD.")
    if parsed < date.today():
        raise HTTPException(status_code=422, detail="Deadline tidak boleh tanggal yang sudah lewat.")
    return value


# ──────────────────────────────────────────────
# Pydantic models (moved from app.py)
# ──────────────────────────────────────────────


class AssignmentCreate(BaseModel):
    manga: str = Field(min_length=2, max_length=150)
    chapter: str = Field(min_length=1, max_length=30)
    staff_id: str | int
    role: Literal["TL", "TS", "TL+TS"]
    rate_per_chapter: int | None = Field(default=None, ge=0, le=1_000_000)
    final_rate: int | None = Field(default=None, ge=0, le=1_000_000)
    deadline_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    raw_mode: Literal["editor_safe", "original"] = "editor_safe"
    raw_source: str | None = Field(default=None, max_length=30)
    raw_id: str | None = Field(default=None, max_length=500)
    raw_pack_mode: Literal["normal", "merge_16000"] = "normal"


class TlTsPairCreate(BaseModel):
    manga: str = Field(min_length=2, max_length=150)
    chapter: str = Field(min_length=1, max_length=30)
    tl_staff_id: str | int
    ts_staff_id: str | int
    tl_rate_per_chapter: int = Field(ge=0, le=1_000_000)
    ts_rate_per_chapter: int = Field(ge=0, le=1_000_000)
    deadline_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    raw_mode: Literal["editor_safe", "original"] = "editor_safe"
    raw_source: str | None = Field(default=None, max_length=30)
    raw_id: str | None = Field(default=None, max_length=500)
    raw_pack_mode: Literal["normal", "merge_16000"] = "normal"

class AssignmentUpdate(BaseModel):
    manga: str = Field(min_length=2, max_length=150)
    chapter: str = Field(min_length=1, max_length=30)
    role: Literal["TL", "TS", "TL+TS"]
    rate_per_chapter: int = Field(ge=0, le=1_000_000)
    deadline_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    raw_mode: Literal["editor_safe", "original"] = "editor_safe"
    raw_source: str | None = Field(default=None, max_length=30)
    raw_id: str | None = Field(default=None, max_length=500)
    raw_pack_mode: Literal["normal", "merge_16000"] = "normal"


class RevisionRequest(BaseModel):
    notes: str = Field(min_length=3, max_length=1500)


# ──────────────────────────────────────────────
# Assignment-specific helpers (moved from app.py)
# ──────────────────────────────────────────────


async def resolve_staff_ticket_channel(staff_id: int, assignment_id: int) -> str | None:
    """Find the private staff ticket from Discord, even for a first dashboard task."""
    connection = await dashboard_db()
    try:
        row = await (await connection.execute(
            "SELECT ticket_channel_id FROM assignments WHERE staff_id=? AND ticket_channel_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (staff_id,),
        )).fetchone()
    finally:
        await connection.close()
    channel_id = str(row[0]) if row and row[0] else None
    if not channel_id:
        channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels") or []
        for channel in channels:
            if channel.get("type") != 0 or "tiket-" not in str(channel.get("name", "")).casefold():
                continue
            topic = str(channel.get("topic") or "")
            owns_overwrite = any(
                str(overwrite.get("id")) == str(staff_id) and overwrite.get("type") == 1
                for overwrite in channel.get("permission_overwrites", [])
            )
            if str(staff_id) in topic or owns_overwrite:
                channel_id = str(channel["id"])
                break
    if channel_id:
        connection = await dashboard_db()
        try:
            await connection.execute(
                "UPDATE assignments SET ticket_channel_id=? WHERE id=?",
                (channel_id, assignment_id),
            )
            await connection.commit()
        finally:
            await connection.close()
    return channel_id


async def send_assignment_notice(
    staff_id: int,
    assignment_id: int,
    payload: AssignmentCreate,
    handoff_note: str | None = None,
):
    if DEV_BYPASS:
        return True
    channel_id = await resolve_staff_ticket_channel(staff_id, assignment_id)
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
            ] + ([{"name": "Bahan dari TL", "value": handoff_note, "inline": False}] if handoff_note else []),
            "footer": {"text": "Buka Staff Panel atau dashboard untuk melihat dan submit tugas."},
        }],
    }
    sent = bool(await discord_api("POST", f"/channels/{channel_id}/messages", message))
    if not sent:
        await operations.enqueue_notification(
            f"assignment:{assignment_id}:created", "assignment", channel_id,
            {"content": message["content"], "embed": message["embeds"][0]},
        )
    return sent


async def send_assignment_update_notice(before: dict, after: dict) -> bool:
    """Tell the assigned staff what changed, only in their private ticket."""
    if DEV_BYPASS or not after.get("staff_id") or not after.get("ticket_channel_id"):
        return bool(DEV_BYPASS)
    fields = []
    comparisons = (
        ("Manga", "manga"),
        ("Chapter", "chapter"),
        ("Role", "role"),
        ("Rate / Chapter", "rate_per_chapter"),
        ("Total Bayaran", "final_rate"),
        ("Deadline", "deadline_at"),
    )
    for label, key in comparisons:
        old_value, new_value = before.get(key), after.get(key)
        if old_value == new_value:
            continue
        if key in {"rate_per_chapter", "final_rate"}:
            old_value = f"Rp {int(old_value or 0):,.0f}".replace(",", ".")
            new_value = f"Rp {int(new_value or 0):,.0f}".replace(",", ".")
        fields.append({
            "name": label,
            "value": f"~~{old_value or 'Tidak ditentukan'}~~ → **{new_value or 'Tidak ditentukan'}**",
            "inline": False,
        })
    message = {
        "content": f"<@{after['staff_id']}>",
        "embeds": [{
            "title": f"📝 Tugas #{after['id']} Diperbarui",
            "description": "Administrator memperbarui detail tugas kamu.",
            "color": 16753920,
            "fields": fields,
            "footer": {"text": "Periksa detail terbaru sebelum melanjutkan pekerjaan."},
        }],
    }
    sent = bool(await discord_api(
        "POST",
        f"/channels/{after['ticket_channel_id']}/messages",
        message,
    ))
    if not sent:
        await operations.enqueue_notification(
            f"assignment:{after['id']}:updated:{hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:12]}",
            "assignment_updated",
            after["ticket_channel_id"],
            {"content": message["content"], "embed": message["embeds"][0]},
        )
    return sent


async def send_ticket_review_notice(assignment: dict, approved: bool, notes: str | None = None):
    """Notify only the private staff ticket; never DM review results."""
    channel_id = assignment.get("ticket_channel_id")
    if DEV_BYPASS:
        return True
    if not channel_id:
        return False
    title = "✅ Tugas Selesai" if approved else "🔄 Tugas Perlu Revisi"
    description = (
        "Hasil kerja telah diperiksa dan **disetujui Administrator**. Bayaran sudah masuk ke rekap gaji."
        if approved
        else f"**{assignment['manga']}** chapter **{assignment['chapter']}** perlu diperbaiki sebelum dikirim ulang."
    )
    fields = [
        {"name": "Manga", "value": assignment["manga"], "inline": False},
        {"name": "Chapter", "value": assignment["chapter"], "inline": True},
        {"name": "Role", "value": assignment["role"], "inline": True},
    ]
    if approved:
        chapter_count = int(assignment.get("chapter_count") or 1)
        total = int(assignment.get("final_rate") or 0)
        rate = int(assignment.get("rate_per_chapter") or (total // chapter_count if chapter_count else total))
        fields.extend([
            {"name": "Jumlah Chapter", "value": str(chapter_count), "inline": True},
            {"name": "Rate per Chapter", "value": f"Rp {rate:,.0f}".replace(",", "."), "inline": True},
            {"name": "Total Bayaran", "value": f"Rp {total:,.0f}".replace(",", "."), "inline": True},
        ])
    if assignment.get("gdrive_link"):
        fields.append({
            "name": "Hasil Google Drive" if approved else "Hasil Sebelumnya",
            "value": assignment["gdrive_link"],
            "inline": False,
        })
    if notes:
        fields.append({"name": "Catatan Admin", "value": notes[:1024], "inline": False})
    message = {
        "content": f"<@{assignment['staff_id']}>",
        "embeds": [{
            "title": title,
            "description": description,
            "color": 5763719 if approved else 16753920,
            "fields": fields,
            "footer": {"text": f"Task #{assignment['id']} • {'Laporan akhir tugas' if approved else 'Perbaiki lalu submit kembali'}"},
        }],
    }
    sent = bool(await discord_api("POST", f"/channels/{channel_id}/messages", message))
    if not sent:
        event = EventType.APPROVED if approved else EventType.REVISION
        await operations.enqueue_notification(
            f"assignment:{assignment['id']}:{event}",
            f"assignment_{event}",
            channel_id,
            {"content": message["content"], "embed": message["embeds"][0]},
        )
    return sent


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────


@router.get("/{assignment_id}/timeline")
async def assignment_timeline(assignment_id: int, _user=Depends(current_user)):
    if not await staff_db.get_assignment(assignment_id):
        raise HTTPException(status_code=404, detail="Tugas tidak ditemukan.")
    return await staff_db.get_assignment_timeline(assignment_id)


@router.get("")
async def assignments(
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    paginated: bool = Query(default=False),
    user=Depends(current_user),
):
    page, page_size, paginated = normalize_paging(page, page_size, paginated)
    # Pair child assignments are payment records; the grouped pair endpoint is
    # their public dashboard representation.
    clauses, params = ["pair_project_id IS NULL"], []
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
        if paginated:
            total = (await (await connection.execute(
                f"SELECT COUNT(*) count FROM assignments{where}", params
            )).fetchone())["count"]
            rows = await (await connection.execute(
                f"SELECT * FROM assignments{where} ORDER BY assigned_at DESC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            )).fetchall()
            return page_payload(await enrich_staff(rows), page, page_size, total)
        rows = await (await connection.execute(
            f"SELECT * FROM assignments{where} ORDER BY assigned_at DESC LIMIT 250", params
        )).fetchall()
        return await enrich_staff(rows)
    finally:
        await connection.close()


@router.post("", status_code=201)
async def create_dashboard_assignment(payload: AssignmentCreate, user=Depends(admin_user)):
    payload.deadline_at = require_current_deadline(payload.deadline_at)
    try:
        chapters = parse_chapters(payload.chapter)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    rate_per_chapter = payload.rate_per_chapter if payload.rate_per_chapter is not None else payload.final_rate
    if rate_per_chapter is None:
        raise HTTPException(status_code=422, detail="Bayaran per chapter wajib diisi.")
    minimum, maximum = await role_rate_range(payload.role)
    if not minimum <= rate_per_chapter <= maximum:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Rate {payload.role} harus Rp{minimum:,.0f}–Rp{maximum:,.0f} per chapter."
                .replace(",", ".")
            ),
        )
    profiles = {item["id"]: item for item in await staff_directory()}
    real_staff_id = await resolve_staff_id_with_fallback(payload.staff_id, profiles)
    if not real_staff_id:
        raise HTTPException(
            status_code=422,
            detail="Staff tidak ditemukan. Pastikan staff sudah memiliki role Staff di Discord, atau coba sinkronisasi ulang daftar staff.",
        )
    payload.staff_id = real_staff_id
    assignment_id = await staff_db.create_assignment(
        manga=payload.manga.strip(),
        chapter=chapter_display(chapters),
        chapters=chapters,
        role=payload.role,
        base_rate=rate_per_chapter,
        rate_per_chapter=rate_per_chapter,
        final_rate=rate_per_chapter * len(chapters),
        multiplier=1.0,
        staff_id=payload.staff_id,
        deadline_at=payload.deadline_at,
        raw_mode=payload.raw_mode,
        raw_source=payload.raw_source,
        raw_manga_id=payload.raw_id,
        raw_pack_mode=payload.raw_pack_mode,
    )
    notice_payload = payload.model_copy(update={
        "chapter": chapter_display(chapters),
        "rate_per_chapter": rate_per_chapter,
        "final_rate": rate_per_chapter * len(chapters),
    })
    notified = await send_assignment_notice(payload.staff_id, assignment_id, notice_payload)
    await audit(user["id"], "assignment.create", "assignment", assignment_id, after={
        **payload.model_dump(),
        "chapters": chapters,
        "chapter_count": len(chapters),
        "rate_per_chapter": rate_per_chapter,
        "final_rate": rate_per_chapter * len(chapters),
        "notified": notified,
    })
    return {"id": assignment_id, "notified": notified}


@router.post("/tl-ts-pair", status_code=201)
async def create_tl_ts_pair(payload: TlTsPairCreate, user=Depends(admin_user)):
    payload.deadline_at = require_current_deadline(payload.deadline_at)
    try:
        chapters = parse_chapters(payload.chapter)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    tl_min, tl_max = await role_rate_range("TL")
    ts_min, ts_max = await role_rate_range("TS")
    if not tl_min <= payload.tl_rate_per_chapter <= tl_max:
        raise HTTPException(
            status_code=422,
            detail=f"Rate TL harus Rp{tl_min:,.0f}–Rp{tl_max:,.0f} per chapter.".replace(",", "."),
        )
    if not ts_min <= payload.ts_rate_per_chapter <= ts_max:
        raise HTTPException(
            status_code=422,
            detail=f"Rate TS harus Rp{ts_min:,.0f}–Rp{ts_max:,.0f} per chapter.".replace(",", "."),
        )
    profiles = {item["id"]: item for item in await staff_directory()}
    real_tl = await resolve_staff_id_with_fallback(payload.tl_staff_id, profiles)
    real_ts = await resolve_staff_id_with_fallback(payload.ts_staff_id, profiles)
    if not real_tl or not real_ts:
        raise HTTPException(
            status_code=422,
            detail="Salah satu staff tidak ditemukan. Pastikan keduanya memiliki role Staff di Discord atau sudah pernah menerima tugas sebelumnya.",
        )
    payload.tl_staff_id = real_tl
    payload.ts_staff_id = real_ts
    if payload.tl_staff_id == payload.ts_staff_id:
        raise HTTPException(
            status_code=422,
            detail="Untuk Pair TL → TS, pilih dua staff berbeda. Gunakan TL+TS untuk satu staff.",
        )
    project = await pair_service.create_project(
        manga=payload.manga.strip(),
        chapters=chapters,
        tl_staff_id=payload.tl_staff_id,
        ts_staff_id=payload.ts_staff_id,
        tl_rate_per_chapter=payload.tl_rate_per_chapter,
        ts_rate_per_chapter=payload.ts_rate_per_chapter,
        deadline_at=payload.deadline_at,
        created_by=user["id"],
        raw_mode=payload.raw_mode,
        raw_source=payload.raw_source,
        raw_manga_id=payload.raw_id,
        raw_pack_mode=payload.raw_pack_mode,
    )
    try:
        channel_id, panel_message_id = await create_pair_workspace(int(project["id"]))
    except RuntimeError as error:
        await pair_service.delete_unpublished_project(int(project["id"]))
        raise HTTPException(status_code=503, detail=str(error))
    first_tl_id = (await pair_service.get_chapter(int(project["chapters"][0]["id"])))[
        "tl_assignment_id"
    ]
    await audit(user["id"], "assignment.pair_create", "pair_project", project["id"], after={
        **payload.model_dump(), "chapters": chapters, "channel_id": channel_id,
    })
    return {
        "tl_assignment_id": first_tl_id,
        "pair_project_id": project["id"],
        "channel_id": channel_id,
        "panel_message_id": panel_message_id,
        "notified": True,
    }


@router.put("/{assignment_id}")
async def update_dashboard_assignment(
    assignment_id: int,
    payload: AssignmentUpdate,
    user=Depends(admin_user),
):
    payload.deadline_at = require_current_deadline(payload.deadline_at)
    before = await staff_db.get_assignment(assignment_id)
    if not before:
        raise HTTPException(status_code=404, detail="Tugas tidak ditemukan.")
    if before["status"] not in {AssignmentStatus.OPEN, AssignmentStatus.CLAIMED, AssignmentStatus.SUBMITTED, AssignmentStatus.REVISION}:
        raise HTTPException(
            status_code=409,
            detail="Tugas yang sudah approved atau paid tidak dapat diubah.",
        )
    try:
        chapters = parse_chapters(payload.chapter)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    minimum, maximum = await role_rate_range(payload.role)
    if not minimum <= payload.rate_per_chapter <= maximum:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Rate {payload.role} harus Rp{minimum:,.0f}–Rp{maximum:,.0f} per chapter."
                .replace(",", ".")
            ),
        )
    final_rate = payload.rate_per_chapter * len(chapters)
    connection = await dashboard_db()
    try:
        await connection.execute("BEGIN IMMEDIATE")
        cursor = await connection.execute(
            """UPDATE assignments
               SET manga=?,chapter=?,chapters=?,chapter_count=?,role=?,
                   base_rate=?,rate_per_chapter=?,final_rate=?,deadline_at=?,raw_mode=?,
                   raw_source=?,raw_manga_id=?,raw_pack_mode=?
               WHERE id=? AND status IN ('open','claimed','submitted','revision')""",
            (
                payload.manga.strip(),
                chapter_display(chapters),
                json.dumps(chapters, ensure_ascii=False),
                len(chapters),
                payload.role,
                payload.rate_per_chapter,
                payload.rate_per_chapter,
                final_rate,
                payload.deadline_at,
                payload.raw_mode,
                payload.raw_source,
                payload.raw_id,
                payload.raw_pack_mode,
                assignment_id,
            ),
        )
        if not cursor.rowcount:
            await connection.rollback()
            raise HTTPException(status_code=409, detail="Status tugas berubah. Muat ulang dashboard.")
        await connection.commit()
    finally:
        await connection.close()
    await staff_db.add_assignment_event(
        assignment_id,
        "updated",
        user["id"],
        "Detail tugas diperbarui melalui dashboard.",
    )
    after = await staff_db.get_assignment(assignment_id)
    notified = await send_assignment_update_notice(before, after)
    await audit(
        user["id"],
        "assignment.update",
        "assignment",
        assignment_id,
        before,
        {**after, "notified": notified},
    )
    return {"ok": True, "assignment": after, "notified": notified}


@router.post("/{assignment_id}/approve")
async def dashboard_approve_assignment(assignment_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        before = await (
            await connection.execute(
                "SELECT * FROM assignments WHERE id=?", (assignment_id,)
            )
        ).fetchone()
    finally:
        await connection.close()
    if not before:
        raise HTTPException(status_code=404, detail="Tugas tidak ditemukan.")
    if before["status"] != AssignmentStatus.SUBMITTED:
        raise HTTPException(
            status_code=409,
            detail=f"Tugas berstatus {before['status']}, bukan submitted.",
        )
    if not await staff_db.approve_assignment(assignment_id):
        raise HTTPException(
            status_code=409, detail="Status tugas berubah. Muat ulang dashboard."
        )
    after = await staff_db.get_assignment(assignment_id)
    next_task = await staff_db.activate_ts_handoff(assignment_id)
    next_notified = False
    if next_task:
        next_payload = AssignmentCreate(
            manga=next_task["manga"],
            chapter=next_task["chapter"],
            staff_id=int(next_task["staff_id"]),
            role="TS",
            rate_per_chapter=int(next_task["rate_per_chapter"]),
            final_rate=int(next_task["final_rate"]),
            deadline_at=next_task.get("deadline_at"),
        )
        next_notified = await send_assignment_notice(
            int(next_task["staff_id"]),
            int(next_task["id"]),
            next_payload,
            handoff_note=next_task.get("admin_notes"),
        )
    notified = await send_ticket_review_notice(after, True)
    await audit(
        user["id"],
        "assignment.approve",
        "assignment",
        assignment_id,
        dict(before),
        {
            **after,
            "notified": notified,
            "ts_assignment_id": next_task.get("id") if next_task else None,
        },
    )
    return {
        "ok": True,
        "notified": notified,
        "ts_assignment_id": next_task.get("id") if next_task else None,
        "ts_notified": next_notified,
    }


@router.post("/{assignment_id}/revision")
async def dashboard_revision_assignment(
    assignment_id: int, payload: RevisionRequest, user=Depends(admin_user)
):
    connection = await dashboard_db()
    try:
        before = await (
            await connection.execute(
                "SELECT * FROM assignments WHERE id=?", (assignment_id,)
            )
        ).fetchone()
    finally:
        await connection.close()
    if not before:
        raise HTTPException(status_code=404, detail="Tugas tidak ditemukan.")
    if before["status"] != AssignmentStatus.SUBMITTED:
        raise HTTPException(
            status_code=409,
            detail=f"Tugas berstatus {before['status']}, bukan submitted.",
        )
    if not await staff_db.revise_assignment(assignment_id, payload.notes.strip()):
        raise HTTPException(
            status_code=409, detail="Status tugas berubah. Muat ulang dashboard."
        )
    after = await staff_db.get_assignment(assignment_id)
    notified = await send_ticket_review_notice(after, False, payload.notes.strip())
    await audit(
        user["id"],
        "assignment.revision",
        "assignment",
        assignment_id,
        dict(before),
        {**after, "notified": notified},
    )
    return {"ok": True, "notified": notified}


class RevokeRequest(BaseModel):
    reason: str = ""


@router.post("/{assignment_id}/revoke")
async def revoke_assignment(
    assignment_id: int,
    payload: RevokeRequest,
    user=Depends(admin_user),
):
    before = await staff_db.get_assignment(assignment_id)
    if not before:
        raise HTTPException(status_code=404, detail="Tugas tidak ditemukan.")
    if before["status"] not in {AssignmentStatus.OPEN, AssignmentStatus.CLAIMED}:
        raise HTTPException(
            status_code=409,
            detail=f"Tugas berstatus {before['status']}, hanya open/claimed yang bisa ditarik.",
        )
    reason = payload.reason.strip() or "Dibatalkan oleh Admin."
    if not await staff_db.revoke_assignment(assignment_id, reason):
        raise HTTPException(status_code=409, detail="Gagal menarik tugas. Status mungkin sudah berubah.")

    # Delete announcement in #staff-tasks
    if before.get("message_id"):
        try:
            await discord_api("DELETE", f"/channels/{STAFF_TASKS_CHANNEL_ID}/messages/{before['message_id']}")
        except Exception:
            pass

    # Notify staff in ticket
    notified = False
    if before.get("staff_id") and before.get("ticket_channel_id"):
        message = {
            "content": f"<@{before['staff_id']}>",
            "embeds": [{
                "title": f"⚠️ Tugas #{assignment_id} Ditarik",
                "description": f"**{before['manga']}** Chapter **{before['chapter']}** telah dibatalkan oleh Admin.",
                "color": 15548997,
                "fields": [{"name": "Alasan", "value": reason, "inline": False}],
            }],
        }
        notified = bool(await discord_api("POST", f"/channels/{before['ticket_channel_id']}/messages", message))

    after = await staff_db.get_assignment(assignment_id)
    await audit(user["id"], "assignment.revoke", "assignment", assignment_id, dict(before), after)
    return {"ok": True, "notified": notified}

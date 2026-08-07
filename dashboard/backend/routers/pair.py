"""Pair router — TL-TS pair projects, chapters, approvals, and revisions."""

import asyncio
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import GUILD_ID, ROLE_ADMIN_ID, ROLE_STAFF_ID, REKRUT_CAT_ID, STAFF_LOG_CHANNEL_ID
import pair_workflow as pair_service
from dashboard.backend.deps import admin_user, audit, dashboard_db, DEV_BYPASS, current_user
from dashboard.backend.helpers import (
    discord_api,
    staff_directory,
    resolve_staff_id_with_fallback,
    resolve_staff_ticket_channel,
    role_rate_range,
)

router = APIRouter(prefix="/api", tags=["pair"])


# --- Pydantic models ---

class TlTsPairCreate(BaseModel):
    manga: str = Field(min_length=2, max_length=150)
    chapter: str = Field(min_length=1, max_length=30)
    tl_staff_id: str
    ts_staff_id: str
    tl_rate_per_chapter: int = Field(ge=0, le=1_000_000)
    ts_rate_per_chapter: int = Field(ge=0, le=1_000_000)
    deadline_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class PairRevisionRequest(BaseModel):
    target: Literal["tl", "ts", "both"]
    notes: str = Field(min_length=3, max_length=1500)


# --- Helpers ---

def pair_panel_payload(project: dict) -> dict:
    state_labels = {
        "waiting_tl": "Menunggu TL", "ready_for_ts": "Siap TS",
        "tl_revision": "Perbaikan TL", "ts_revision": "Perbaikan TS",
        "both_revision": "Perbaikan TL + TS", "final_review": "Review Final",
        "completed": "Selesai",
    }
    progress = "\n".join(
        f"{'✅' if item['status'] == 'completed' else '🔄' if 'revision' in item['status'] else '•'} "
        f"**Chapter {item['chapter']}** — {state_labels.get(item['status'], item['status'])}"
        for item in project["chapters"]
    )
    return {
        "embeds": [{
            "title": f"Kolaborasi TL–TS • {project['manga']}",
            "description": (
                f"<@{project['tl_staff_id']}> sebagai **Translator** dan <@{project['ts_staff_id']}> "
                "sebagai **Typesetter** bekerja dalam satu ruang.\n"
                "Gaji setiap chapter dilepas untuk keduanya setelah hasil final disetujui Administrator."
            ),
            "color": 6253567,
            "fields": [
                {"name": "Progress", "value": progress, "inline": False},
                {"name": "Rate TL", "value": f"Rp {project['tl_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Rate TS", "value": f"Rp {project['ts_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Deadline", "value": project.get("deadline_at") or "Tidak ditentukan", "inline": True},
            ],
            "footer": {"text": f"Pair Project #{project['id']} • Gunakan tombol sesuai peran"},
        }],
        "components": [{"type": 1, "components": [
            {"type": 2, "style": 1, "label": "Submit Hasil TL", "custom_id": f"pair:tl:{project['id']}:v2"},
            {"type": 2, "style": 3, "label": "Submit Final TS", "custom_id": f"pair:ts:{project['id']}:v2"},
            {"type": 2, "style": 4, "label": "Minta Perbaikan TL", "custom_id": f"pair:tl-revision:{project['id']}:v2"},
            {"type": 2, "style": 2, "label": "Lihat Status Chapter", "custom_id": f"pair:status:{project['id']}:v2"},
            {"type": 2, "style": 2, "label": "Download RAW", "custom_id": f"pair:raw:{project['id']}:v2"},
        ]}],
        "allowed_mentions": {"users": [str(project["tl_staff_id"]), str(project["ts_staff_id"])]},
    }


async def create_pair_workspace(project_id: int) -> tuple[str, str]:
    project = await pair_service.get_project(project_id)
    if not project:
        raise RuntimeError("Pair project tidak ditemukan setelah dibuat.")
    reusable = await pair_service.find_reusable_workspace(project["manga"])
    channel = None
    created_new_channel = False
    if reusable:
        channel = await discord_api("GET", f"/channels/{reusable['channel_id']}")
    if channel:
        slug = re.sub(r"[^a-z0-9]+", "-", project["manga"].casefold()).strip("-")[:70] or "project"
        await discord_api("PATCH", f"/channels/{channel['id']}", {
            "name": f"🔒・project-{slug}",
            "topic": f"Ruang permanen {project['manga']} | Pair aktif #{project_id} | TL:{project['tl_staff_id']} | TS:{project['ts_staff_id']}",
        })
        staff_allow = str((1 << 10) | (1 << 11) | (1 << 14) | (1 << 15) | (1 << 16))
        for staff_id in {str(project["tl_staff_id"]), str(project["ts_staff_id"])}:
            await discord_api("PUT", f"/channels/{channel['id']}/permissions/{staff_id}", {
                "type": 1, "allow": staff_allow, "deny": "0",
            })
        current_staff = {str(project["tl_staff_id"]), str(project["ts_staff_id"])}
        for overwrite in channel.get("permission_overwrites", []):
            overwrite_id = str(overwrite.get("id") or "")
            if int(overwrite.get("type", 0)) == 1 and overwrite_id not in current_staff:
                await discord_api("DELETE", f"/channels/{channel['id']}/permissions/{overwrite_id}")
        await discord_api("PUT", f"/channels/{channel['id']}/permissions/{ROLE_STAFF_ID}", {
            "type": 0, "allow": "0", "deny": str(1 << 10),
        })
        if reusable.get("panel_message_id"):
            await discord_api("DELETE", f"/channels/{channel['id']}/pins/{reusable['panel_message_id']}")
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", project["manga"].casefold()).strip("-")[:70] or "project"
        staff_allow = str((1 << 10) | (1 << 11) | (1 << 14) | (1 << 15) | (1 << 16))
        admin_allow = str(int(staff_allow) | (1 << 4) | (1 << 13))
        channel = await discord_api("POST", f"/guilds/{GUILD_ID}/channels", {
        "name": f"🔒・project-{slug}",
        "type": 0,
        "parent_id": str(REKRUT_CAT_ID),
        "topic": f"Ruang permanen {project['manga']} | Pair aktif #{project_id} | TL:{project['tl_staff_id']} | TS:{project['ts_staff_id']}",
        "permission_overwrites": [
            {"id": str(GUILD_ID), "type": 0, "deny": str(1 << 10), "allow": "0"},
            {"id": str(ROLE_STAFF_ID), "type": 0, "deny": str(1 << 10), "allow": "0"},
            {"id": str(project["tl_staff_id"]), "type": 1, "allow": staff_allow, "deny": "0"},
            {"id": str(project["ts_staff_id"]), "type": 1, "allow": staff_allow, "deny": "0"},
            {"id": str(ROLE_ADMIN_ID), "type": 0, "allow": admin_allow, "deny": "0"},
        ],
        })
        if not channel:
            raise RuntimeError("Discord gagal membuat channel proyek privat.")
        created_new_channel = True
    message = await discord_api("POST", f"/channels/{channel['id']}/messages", {
        "content": f"<@{project['tl_staff_id']}> <@{project['ts_staff_id']}> ruang kolaborasi kalian sudah siap.",
        **pair_panel_payload(project),
    })
    if not message:
        if created_new_channel:
            await discord_api("DELETE", f"/channels/{channel['id']}")
        raise RuntimeError("Discord gagal membuat panel pair.")
    await discord_api("PUT", f"/channels/{channel['id']}/pins/{message['id']}")
    await pair_service.set_workspace(project_id, int(channel["id"]), int(message["id"]))
    if reusable and str(reusable["channel_id"]) == str(channel["id"]):
        await pair_service.record_workspace_reuse(project_id, int(reusable["id"]))
    return str(channel["id"]), str(message["id"])


async def refresh_pair_workspace_rest(project_id: int) -> None:
    project = await pair_service.get_project(project_id)
    if not project or not project.get("channel_id") or not project.get("panel_message_id") or DEV_BYPASS:
        return
    await discord_api(
        "PATCH", f"/channels/{project['channel_id']}/messages/{project['panel_message_id']}",
        pair_panel_payload(project),
    )


async def remove_pair_review_rest(chapter: dict) -> None:
    if chapter.get("review_message_id") and not DEV_BYPASS:
        await discord_api("DELETE", f"/channels/{STAFF_LOG_CHANNEL_ID}/messages/{chapter['review_message_id']}")
    await pair_service.set_review_message(int(chapter["id"]), None)


async def complete_pair_review_rest(chapter: dict) -> None:
    if not chapter.get("review_message_id") or DEV_BYPASS:
        return
    await discord_api(
        "PATCH", f"/channels/{STAFF_LOG_CHANNEL_ID}/messages/{chapter['review_message_id']}",
        {"embeds": [{
            "title": f"✅ Pair Selesai • {chapter['manga']} Chapter {chapter['chapter']}",
            "description": "Hasil final disetujui. Gaji TL dan TS masuk ke saldo secara bersamaan.",
            "color": 5763719,
            "fields": [
                {"name": "Translator", "value": f"<@{chapter['tl_staff_id']}> • Rp {chapter['tl_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Typesetter", "value": f"<@{chapter['ts_staff_id']}> • Rp {chapter['ts_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Hasil TL", "value": chapter.get("tl_link") or "Tidak tersedia", "inline": False},
                {"name": "Hasil Final", "value": chapter.get("final_link") or "Tidak tersedia", "inline": False},
            ],
        }], "components": []},
    )


async def send_pair_ticket_notice(chapter: dict, staff_id: int, role: str, approved: bool, notes: str | None = None) -> bool:
    assignment_id = int(chapter["tl_assignment_id"] if role == "TL" else chapter["ts_assignment_id"])
    channel_id = await resolve_staff_ticket_channel(staff_id, assignment_id)
    if DEV_BYPASS:
        return True
    if not channel_id:
        return False
    rate = int(chapter["tl_rate_per_chapter"] if role == "TL" else chapter["ts_rate_per_chapter"])
    fields = [
        {"name": "Manga", "value": chapter["manga"], "inline": False},
        {"name": "Chapter", "value": chapter["chapter"], "inline": True},
        {"name": "Role", "value": role, "inline": True},
        {"name": "Ruang Proyek", "value": f"<#{chapter['channel_id']}>", "inline": False},
    ]
    if approved:
        fields.extend([
            {"name": "Bayaran", "value": f"Rp {rate:,.0f}".replace(",", "."), "inline": True},
            {"name": "Hasil Final", "value": chapter.get("final_link") or "Tidak tersedia", "inline": False},
        ])
    elif notes:
        fields.append({"name": "Catatan Revisi", "value": notes, "inline": False})
    return bool(await discord_api("POST", f"/channels/{channel_id}/messages", {
        "content": f"<@{staff_id}>",
        "embeds": [{
            "title": "✅ Chapter Pair Selesai" if approved else f"🔄 Perbaikan Pair untuk {role}",
            "description": (
                "Hasil final disetujui Administrator dan bayaran masuk ke saldo."
                if approved else "Administrator meminta perbaikan sebelum review final."
            ),
            "color": 5763719 if approved else 16753920,
            "fields": fields,
        }],
        "allowed_mentions": {"users": [str(staff_id)]},
    }))


# --- Endpoints ---

@router.post("/assignments/tl-ts-pair", status_code=201)
async def create_tl_ts_pair(payload: TlTsPairCreate, user=Depends(admin_user)):
    from chapter_utils import chapter_display, parse_chapters
    try:
        chapters = parse_chapters(payload.chapter)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    tl_min, tl_max = await role_rate_range("TL")
    ts_min, ts_max = await role_rate_range("TS")
    if not tl_min <= payload.tl_rate_per_chapter <= tl_max:
        raise HTTPException(status_code=422, detail=f"Rate TL harus Rp{tl_min:,.0f}–Rp{tl_max:,.0f} per chapter.".replace(",", "."))
    if not ts_min <= payload.ts_rate_per_chapter <= ts_max:
        raise HTTPException(status_code=422, detail=f"Rate TS harus Rp{ts_min:,.0f}–Rp{ts_max:,.0f} per chapter.".replace(",", "."))
    profiles = {item["id"]: item for item in await staff_directory()}
    real_tl = await resolve_staff_id_with_fallback(payload.tl_staff_id, profiles)
    real_ts = await resolve_staff_id_with_fallback(payload.ts_staff_id, profiles)
    if not real_tl or not real_ts:
        raise HTTPException(status_code=422, detail="Salah satu staff tidak ditemukan. Pastikan keduanya memiliki role Staff di Discord atau sudah pernah menerima tugas sebelumnya.")
    payload.tl_staff_id = real_tl
    payload.ts_staff_id = real_ts
    if payload.tl_staff_id == payload.ts_staff_id:
        raise HTTPException(status_code=422, detail="Untuk Pair TL → TS, pilih dua staff berbeda. Gunakan TL+TS untuk satu staff.")
    project = await pair_service.create_project(
        manga=payload.manga.strip(), chapters=chapters,
        tl_staff_id=payload.tl_staff_id, ts_staff_id=payload.ts_staff_id,
        tl_rate_per_chapter=payload.tl_rate_per_chapter,
        ts_rate_per_chapter=payload.ts_rate_per_chapter,
        deadline_at=payload.deadline_at, created_by=user["id"],
    )
    try:
        channel_id, panel_message_id = await create_pair_workspace(int(project["id"]))
    except RuntimeError as error:
        await pair_service.delete_unpublished_project(int(project["id"]))
        raise HTTPException(status_code=503, detail=str(error))
    first_tl_id = (await pair_service.get_chapter(int(project["chapters"][0]["id"]))) ["tl_assignment_id"]
    await audit(user["id"], "assignment.pair_create", "pair_project", project["id"], after={
        **payload.model_dump(), "chapters": chapters, "channel_id": channel_id,
    })
    return {
        "tl_assignment_id": first_tl_id, "pair_project_id": project["id"],
        "channel_id": channel_id, "panel_message_id": panel_message_id, "notified": True,
    }


@router.get("/pair-projects")
async def pair_projects(user=Depends(current_user)):
    rows = await pair_service.list_projects(None if user["role"] == "admin" else int(user["id"]))
    directory = {str(item["id"]): item for item in await staff_directory()}
    for item in rows:
        tl = directory.get(str(item["tl_staff_id"]), {})
        ts = directory.get(str(item["ts_staff_id"]), {})
        item["tl_staff_name"] = tl.get("username") or str(item["tl_staff_id"])
        item["ts_staff_name"] = ts.get("username") or str(item["ts_staff_id"])
        item["tl_staff_id"], item["ts_staff_id"] = str(item["tl_staff_id"]), str(item["ts_staff_id"])
        item["channel_id"] = str(item["channel_id"]) if item.get("channel_id") else None
    return rows


@router.post("/pair-chapters/{chapter_id}/approve")
async def dashboard_pair_approve(chapter_id: int, user=Depends(admin_user)):
    chapter = await pair_service.approve_final(chapter_id, int(user["id"]))
    if not chapter:
        raise HTTPException(status_code=409, detail="Chapter bukan dalam status review final atau sudah diproses.")
    notices = await asyncio.gather(
        send_pair_ticket_notice(chapter, int(chapter["tl_staff_id"]), "TL", True),
        send_pair_ticket_notice(chapter, int(chapter["ts_staff_id"]), "TS", True),
    )
    await refresh_pair_workspace_rest(int(chapter["project_id"]))
    await complete_pair_review_rest(chapter)
    await audit(user["id"], "pair.final_approve", "pair_chapter", chapter_id, after={
        "project_id": chapter["project_id"], "tl_notified": notices[0], "ts_notified": notices[1]
    })
    return {"ok": True, "chapter": chapter, "notified": all(notices)}


@router.post("/pair-chapters/{chapter_id}/revision")
async def dashboard_pair_revision(chapter_id: int, payload: PairRevisionRequest, user=Depends(admin_user)):
    before = await pair_service.get_chapter(chapter_id)
    if not await pair_service.request_revision(
        chapter_id, int(user["id"]), payload.target, payload.notes.strip(), admin=True
    ):
        raise HTTPException(status_code=409, detail="Chapter bukan dalam status review final atau sudah diproses.")
    chapter = await pair_service.get_chapter(chapter_id)
    if before:
        await remove_pair_review_rest(before)
    await refresh_pair_workspace_rest(int(chapter["project_id"]))
    targets = []
    if payload.target in {"tl", "both"}:
        targets.append(send_pair_ticket_notice(chapter, int(chapter["tl_staff_id"]), "TL", False, payload.notes.strip()))
    if payload.target in {"ts", "both"}:
        targets.append(send_pair_ticket_notice(chapter, int(chapter["ts_staff_id"]), "TS", False, payload.notes.strip()))
    notices = await asyncio.gather(*targets) if targets else []
    await audit(user["id"], f"pair.revision_{payload.target}", "pair_chapter", chapter_id, after={
        "notes": payload.notes.strip(), "notified": all(notices)
    })
    return {"ok": True, "chapter": chapter, "notified": all(notices)}


@router.get("/pair-projects/{project_id}/timeline")
async def pair_project_timeline(project_id: int, user=Depends(current_user)):
    project = await pair_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Pair project tidak ditemukan.")
    if user["role"] != "admin" and int(user["id"]) not in {int(project["tl_staff_id"]), int(project["ts_staff_id"])}:
        raise HTTPException(status_code=403, detail="Kamu bukan anggota pair project ini.")
    return await pair_service.timeline(project_id)

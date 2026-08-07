"""Recruitment router — Recruitment settings, submissions, and ticket management."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import (
    GUILD_ID, REKRUT_CAT_ID, ROLE_STAFF_ID,
    RECRUITMENT_TEST_EXPIRES_AT, RECRUITMENT_TEST_URL,
    RECRUITMENT_TL_EXAMPLE_URL, RECRUITMENT_TS_ASSETS_URL,
)
import database as staff_db
import operations
from dashboard.backend.deps import admin_user, audit, dashboard_db, DEV_BYPASS
from enums import AssignmentStatus, PayoutStatus, BonusStatus
from dashboard.backend.helpers import discord_api

router = APIRouter(prefix="/api/recruitment", tags=["recruitment"])


# --- Pydantic models ---

class RecruitmentSettingsUpdate(BaseModel):
    tl: bool
    ts: bool
    tl_ts: bool


class RecruitmentCloseRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


# --- Helpers ---

def recruitment_panel_payload(settings: dict[str, bool]) -> tuple[dict, list]:
    enabled = [position for position in ("TL", "TS", "TL+TS") if settings[position]]
    fields = []
    descriptions = {
        "TL": ("💬 TL — Translator", "Menerjemahkan dialog Bahasa Inggris ke Bahasa Indonesia secara natural."),
        "TS": ("🎨 TS — Typesetter / Editor", "Menangani cleaning, redrawing, dan typesetting chapter."),
        "TL+TS": ("✨ TL + TS — Keduanya", "Mengerjakan paket tes Translator dan Typesetter."),
    }
    for position in ("TL", "TS", "TL+TS"):
        name, value = descriptions[position]
        is_open = position in enabled
        fields.append({
            "name": name if is_open else f"{name} • CLOSED",
            "value": (
                value
                if is_open
                else f"{value}\n🔒 **Pendaftaran posisi ini sedang ditutup.**"
            ),
            "inline": False,
        })
    fields.append({
        "name": "📌 Persyaratan",
        "value": (
            "• Memiliki waktu luang dan bertanggung jawab.\n"
            "• Bisa berkomunikasi serta menerima revisi.\n"
            "• PC/laptop sangat disarankan untuk TS."
        ),
        "inline": False,
    })
    if enabled:
        fields.append({
            "name": "🔒 Tiket Privat",
            "value": "Tiket hanya dapat dilihat pelamar, administrator, dan bot.",
            "inline": False,
        })
    embed = {
        "title": "Ryukomik | Staff Recruitment",
        "description": (
            "Halo! Ryukomik sedang membuka kesempatan untuk bergabung sebagai staff scanlation."
            if enabled
            else "Rekrutmen staff sedang ditutup sementara. Silakan pantau panel ini untuk pembukaan berikutnya."
        ),
        "color": 5793266,
        "fields": fields,
        "footer": {"text": "Ryukomik Official • Recruitment System"},
    }
    components = [{
        "type": 1,
        "components": [{
            "type": 2,
            "style": 1,
            "label": "Buat Tiket Pendaftaran",
            "emoji": {"name": "📩"},
            "custom_id": "recruitment:create_ticket:v1",
            "disabled": not enabled,
        }],
    }]
    return embed, components


async def update_discord_recruitment_panel(settings: dict[str, bool]) -> bool:
    if DEV_BYPASS:
        return True
    channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels") or []
    candidates = [
        channel for channel in channels
        if channel.get("type") == 0
        and (
            "staff-rekrutmen" in channel.get("name", "").casefold()
            or "staff-recruitment" in channel.get("name", "").casefold()
        )
    ]
    embed, components = recruitment_panel_payload(settings)
    for channel in candidates:
        messages = await discord_api(
            "GET", f"/channels/{channel['id']}/messages?limit=100"
        ) or []
        for message in messages:
            title = ((message.get("embeds") or [{}])[0].get("title") or "")
            if message.get("author", {}).get("bot") and "Staff Recruitment" in title:
                updated = await discord_api(
                    "PATCH",
                    f"/channels/{channel['id']}/messages/{message['id']}",
                    {"embeds": [embed], "components": components},
                )
                return bool(updated)
    return False


# --- Endpoints ---

@router.get("/settings")
async def recruitment_settings(_user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute(
            """SELECT position,enabled,updated_at,updated_by
               FROM recruitment_position_settings ORDER BY position"""
        )).fetchall()
        counts = await (await connection.execute(
            """SELECT position,COUNT(*) active_count
               FROM recruitment_submissions
               WHERE status='submitted' GROUP BY position"""
        )).fetchall()
    finally:
        await connection.close()
    count_map = {row["position"]: int(row["active_count"]) for row in counts}
    row_map = {row["position"]: row for row in rows}
    try:
        material_expiry = datetime.fromisoformat(RECRUITMENT_TEST_EXPIRES_AT.replace("Z", "+00:00"))
        material_hours = (material_expiry.replace(tzinfo=material_expiry.tzinfo or ZoneInfo("UTC")) - datetime.now(ZoneInfo("UTC"))).total_seconds() / 3600
        material_status = "expired" if material_hours <= 0 else "expiring" if material_hours <= 24 else "active"
    except ValueError:
        material_hours, material_status = None, "unknown"
    return {
        "positions": [
            {
                "position": position,
                "enabled": bool(row_map[position]["enabled"]) if position in row_map else True,
                "active_count": count_map.get(position, 0),
                "updated_at": row_map[position]["updated_at"] if position in row_map else None,
                "updated_by": row_map[position]["updated_by"] if position in row_map else None,
            }
            for position in ("TL", "TS", "TL+TS")
        ],
        "open": any(
            bool(row_map[position]["enabled"]) if position in row_map else True
            for position in ("TL", "TS", "TL+TS")
        ),
        "test_material": {
            "url": RECRUITMENT_TEST_URL,
            "tl_example_url": RECRUITMENT_TL_EXAMPLE_URL,
            "ts_assets_url": RECRUITMENT_TS_ASSETS_URL,
            "expires_at": RECRUITMENT_TEST_EXPIRES_AT,
            "hours_remaining": round(material_hours, 1) if material_hours is not None else None,
            "status": material_status,
        },
    }


@router.get("/submissions")
async def recruitment_submissions(_user=Depends(admin_user)):
    channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels")
    result = []
    for channel in channels if isinstance(channels, list) else []:
        topic = str(channel.get("topic") or "")
        owner = re.search(r"applicant_id=(\d+)", topic)
        if channel.get("type") != 0 or str(channel.get("parent_id")) != str(REKRUT_CAT_ID) or not owner:
            continue
        member = await discord_api("GET", f"/guilds/{GUILD_ID}/members/{owner.group(1)}")
        if isinstance(member, dict) and str(ROLE_STAFF_ID) in {str(role) for role in member.get("roles", [])}:
            continue
        profile = member.get("user", {}) if isinstance(member, dict) else {}
        applicant_name = str(member.get("nick") or profile.get("global_name") or profile.get("username") or f"User {owner.group(1)}") if isinstance(member, dict) else f"User {owner.group(1)}"
        result.append({
            "id": str(channel["id"]), "applicant_id": owner.group(1),
            "applicant_name": applicant_name,
            "ticket_name": str(channel.get("name") or "tiket-pendaftaran"),
            "position": re.search(r"position=([^|]+)", topic).group(1).strip() if "position=" in topic else "Belum dipilih",
            "ticket_channel_id": str(channel["id"]), "status": "submitted", "submitted_at": "",
        })
    return result


@router.post("/submissions/{submission_id}/close")
async def close_recruitment_submission(submission_id: int, payload: RecruitmentCloseRequest, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        channel = await discord_api("GET", f"/channels/{submission_id}")
        owner = re.search(r"applicant_id=(\d+)", str(channel.get("topic") or "")) if isinstance(channel, dict) else None
        if not owner:
            raise HTTPException(404, "Tiket pendaftaran tidak ditemukan.")
        applicant_id = owner.group(1)
        member = await discord_api("GET", f"/guilds/{GUILD_ID}/members/{applicant_id}")
        if isinstance(member, dict) and str(ROLE_STAFF_ID) in {str(role) for role in member.get("roles", [])}:
            raise HTTPException(409, "Pelamar sudah menjadi Staff; tiket ini adalah workspace staff dan tidak dapat ditutup dari Rekrutmen.")
        await connection.execute(
            "UPDATE recruitment_submissions SET status='closed',reviewed_at=CURRENT_TIMESTAMP,reviewed_by=?,notes=COALESCE(notes,'') || ? WHERE ticket_channel_id=? AND status='submitted'",
            (user["id"], "\n[Ditutup admin] " + payload.reason.strip(), submission_id),
        )
        await connection.commit()
    finally:
        await connection.close()
    deleted = await discord_api("DELETE", f"/channels/{submission_id}")
    if deleted is None:
        raise HTTPException(503, "Status pendaftaran tersimpan, tetapi channel tiket gagal dihapus. Coba lagi dari dashboard.")
    await audit(user["id"], "recruitment.close", "ticket", submission_id, None, {"reason": payload.reason.strip()})
    return {"ok": True}


@router.put("/settings")
async def update_recruitment_settings(
    payload: RecruitmentSettingsUpdate,
    user=Depends(admin_user),
):
    before = await staff_db.get_recruitment_position_settings()
    requested = {
        "TL": payload.tl,
        "TS": payload.ts,
        "TL+TS": payload.tl_ts,
    }
    after = await staff_db.set_recruitment_position_settings(requested, user["id"])
    synced = False
    sync_error = None
    try:
        synced = await update_discord_recruitment_panel(after)
        if not synced:
            sync_error = "Panel rekrutmen aktif tidak ditemukan."
    except Exception as exc:
        sync_error = str(exc)[:500]
    if sync_error:
        await operations.record_event(
            "recruitment",
            "warning",
            "Pengaturan tersimpan tetapi panel Discord belum tersinkron.",
            {"error": sync_error, "settings": after},
        )
    await audit(
        user["id"],
        "recruitment.settings.update",
        "recruitment_settings",
        "positions",
        before,
        {**after, "discord_synced": synced},
    )
    return {"ok": True, "settings": after, "discord_synced": synced}

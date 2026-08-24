"""Recruitment router — Recruitment settings, submissions, and ticket management."""

import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import (
    GUILD_ID, REKRUT_CAT_ID, ROLE_STAFF_ID,
    RECRUITMENT_TEST_URL,
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


class RecruitmentMaterialsUpdate(BaseModel):
    test_url: str = Field(min_length=10, max_length=2000)
    tl_example_url: str = Field(min_length=10, max_length=2000)
    ts_assets_url: str = Field(min_length=10, max_length=2000)


class RecruitmentAnnouncementRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1800)


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


def _material_defaults() -> dict[str, str]:
    return {
        "test_url": RECRUITMENT_TEST_URL,
        "tl_example_url": RECRUITMENT_TL_EXAMPLE_URL,
        "ts_assets_url": RECRUITMENT_TS_ASSETS_URL,
    }


def _validate_material_links(links: dict[str, str]) -> None:
    for value in links.values():
        if not re.match(r"^https?://", value, re.IGNORECASE):
            raise HTTPException(422, "Semua bahan harus berupa link http/https yang valid.")


async def _active_recruitment_channels() -> list[dict]:
    channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels") or []
    result = []
    for channel in channels if isinstance(channels, list) else []:
        topic = str(channel.get("topic") or "")
        owner = re.search(r"applicant_id=(\d+)", topic)
        if channel.get("type") != 0 or str(channel.get("parent_id")) != str(REKRUT_CAT_ID) or not owner:
            continue
        member = await discord_api("GET", f"/guilds/{GUILD_ID}/members/{owner.group(1)}")
        roles = {str(role) for role in member.get("roles", [])} if isinstance(member, dict) else set()
        if str(ROLE_STAFF_ID) not in roles:
            result.append(channel)
    return result


async def _refresh_material_buttons(links: dict[str, str]) -> int:
    """Replace URL buttons on existing applicant test cards without restarting the bot."""
    updated = 0
    position_ids = {"TL": "tl", "TS": "ts", "TL+TS": "tl_ts"}
    for channel in await _active_recruitment_channels():
        match = re.search(r"position=(TL\+TS|TL|TS)", str(channel.get("topic") or ""), re.IGNORECASE)
        if not match:
            continue
        position = match.group(1).upper()
        link_buttons = [{"type": 2, "style": 5, "label": "Download Bahan Tes", "url": links["test_url"]}]
        if position in {"TL", "TL+TS"}:
            link_buttons.append({"type": 2, "style": 5, "label": "Contoh TL", "url": links["tl_example_url"]})
        if position in {"TS", "TL+TS"}:
            link_buttons.append({"type": 2, "style": 5, "label": "Asset TS", "url": links["ts_assets_url"]})
        messages = await discord_api("GET", f"/channels/{channel['id']}/messages?limit=100") or []
        for message in messages if isinstance(messages, list) else []:
            title = str(((message.get("embeds") or [{}])[0].get("title") or "")).casefold()
            if title.startswith(("tes rekrutmen ", "bahan tes ")):
                result = await discord_api("PATCH", f"/channels/{channel['id']}/messages/{message['id']}", {
                    "components": [
                        {"type": 1, "components": link_buttons},
                        {"type": 1, "components": [{
                            "type": 2, "style": 3, "label": "Submit Hasil Tes",
                            "custom_id": f"recruitment:submit:{position_ids[position]}:v1",
                        }]},
                    ]
                })
                if result:
                    updated += 1
                break
    return updated


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
    finally:
        await connection.close()
    count_map = {position: 0 for position in ("TL", "TS", "TL+TS")}
    for channel in await _active_recruitment_channels():
        match = re.search(r"position=(TL\+TS|TL|TS)", str(channel.get("topic") or ""), re.IGNORECASE)
        if match:
            count_map[match.group(1).upper()] += 1
    row_map = {row["position"]: row for row in rows}
    materials = await staff_db.get_recruitment_material_settings(_material_defaults())
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
            "url": materials["test_url"],
            "tl_example_url": materials["tl_example_url"],
            "ts_assets_url": materials["ts_assets_url"],
            "expires_at": None,
            "hours_remaining": None,
            "status": "active",
            "updated_at": materials.get("updated_at"),
        },
    }


@router.put("/materials")
async def update_recruitment_materials(payload: RecruitmentMaterialsUpdate, user=Depends(admin_user)):
    links = {key: value.strip() for key, value in payload.model_dump().items()}
    _validate_material_links(links)
    before = await staff_db.get_recruitment_material_settings(_material_defaults())
    after = await staff_db.set_recruitment_material_settings(links, user["id"])
    refreshed = await _refresh_material_buttons(links)
    await audit(user["id"], "recruitment.materials.update", "recruitment_materials", "links", before, {**after, "cards_refreshed": refreshed})
    return {"ok": True, "materials": after, "cards_refreshed": refreshed}


@router.post("/announcements")
async def send_recruitment_announcement(payload: RecruitmentAnnouncementRequest, user=Depends(admin_user)):
    sent, failed = 0, 0
    for channel in await _active_recruitment_channels():
        result = await discord_api("POST", f"/channels/{channel['id']}/messages", {
            "embeds": [{
                "title": "📢 Pengumuman Rekrutmen",
                "description": payload.message.strip(),
                "color": 5793266,
                "footer": {"text": "Ryukomik Recruitment • Pesan Administrator"},
            }],
            "allowed_mentions": {"parse": []},
        })
        if result:
            sent += 1
        else:
            failed += 1
    await audit(user["id"], "recruitment.announcement.send", "recruitment", "active", None, {"sent": sent, "failed": failed})
    return {"ok": failed == 0, "sent": sent, "failed": failed}


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

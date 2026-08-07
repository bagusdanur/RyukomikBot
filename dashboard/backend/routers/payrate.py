"""Payrate router — Staff payrate management and Discord panel sync."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from config import GUILD_ID, ROLE_STAFF_ID, STAFF_PAYRATE_CHANNEL_ID
from dashboard.backend.deps import (
    admin_user, audit, dashboard_db, DEV_BYPASS, current_user,
    DEFAULT_RATE_RANGES, PayrateUpdate,
)
from dashboard.backend.helpers import discord_api
from dashboard.backend.helpers import role_rate_range

router = APIRouter(prefix="/api", tags=["payrate"])


# --- Helpers ---

def payrate_embed_payload(ranges: dict[str, tuple[int, int]]) -> dict:
    labels = {
        "TL": "Translator (TL)",
        "TS": "Editor / Typesetter (TS)",
        "TL+TS": "TL + TS (Keduanya)",
    }
    return {
        "title": "💰 Ryukomik | Staff Pay Rates",
        "description": (
            "Rate berikut berlaku sebagai panduan bayaran per chapter. "
            "Nominal tugas tetap ditampilkan sebelum staff mulai mengerjakan."
        ),
        "color": 8162559,
        "fields": [
            {
                "name": labels[role],
                "value": (
                    f"**Rp{ranges[role][0]:,.0f} – Rp{ranges[role][1]:,.0f} / chapter**"
                    .replace(",", ".")
                ),
                "inline": False,
            }
            for role in ("TL", "TS", "TL+TS")
        ] + [{
            "name": "Ketentuan",
            "value": (
                "• Rate final ditentukan Administrator saat tugas dibuat.\n"
                "• Tugas multi-chapter dihitung: rate per chapter × jumlah chapter.\n"
                "• Perubahan rate resmi tidak mengubah tugas lama secara otomatis."
            ),
            "inline": False,
        }],
        "footer": {"text": "Ryukomik Official • Informasi rate staff terbaru"},
    }


async def update_discord_payrate_panel() -> bool:
    if DEV_BYPASS:
        return True
    ranges = {role: await role_rate_range(role) for role in DEFAULT_RATE_RANGES}
    messages = await discord_api(
        "GET", f"/channels/{STAFF_PAYRATE_CHANNEL_ID}/messages?limit=100"
    )
    embed = payrate_embed_payload(ranges)
    for message in messages or []:
        title = ((message.get("embeds") or [{}])[0].get("title") or "")
        if message.get("author", {}).get("bot") and "Staff Pay Rates" in title:
            return bool(await discord_api(
                "PATCH",
                f"/channels/{STAFF_PAYRATE_CHANNEL_ID}/messages/{message['id']}",
                {"embeds": [embed]},
            ))
    return bool(await discord_api(
        "POST",
        f"/channels/{STAFF_PAYRATE_CHANNEL_ID}/messages",
        {"embeds": [embed]},
    ))


async def broadcast_payrate_to_staff(role: str, min_rate: int, max_rate: int) -> int:
    if DEV_BYPASS:
        return 0
    members = await discord_api("GET", f"/guilds/{GUILD_ID}/members?limit=1000") or []
    staff_ids = {
        int(member["user"]["id"])
        for member in members
        if ROLE_STAFF_ID in {int(value) for value in member.get("roles", [])}
    }
    channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels") or []
    ticket_map = {}
    for channel in channels:
        if channel.get("type") != 0 or "tiket-" not in channel.get("name", "").casefold():
            continue
        topic = channel.get("topic") or ""
        for staff_id in staff_ids:
            owns_overwrite = any(
                str(overwrite.get("id")) == str(staff_id)
                and overwrite.get("type") == 1
                for overwrite in channel.get("permission_overwrites", [])
            )
            if str(staff_id) in topic or owns_overwrite:
                ticket_map.setdefault(staff_id, channel["id"])
    labels = {"TL": "Translator (TL)", "TS": "Editor / Typesetter (TS)", "TL+TS": "TL + TS (Keduanya)"}
    sent = 0
    for staff_id, channel_id in ticket_map.items():
        message = {
            "embeds": [{
                "title": "📢 Payrate Staff Diperbarui",
                "description": (
                    f"Range **{labels[role]}** sekarang "
                    f"**Rp{min_rate:,.0f} – Rp{max_rate:,.0f} / chapter**."
                ).replace(",", "."),
                "color": 6253567,
                "footer": {"text": "Tugas lama tidak berubah • Berlaku untuk tugas berikutnya"},
            }],
        }
        if await discord_api("POST", f"/channels/{channel_id}/messages", message):
            sent += 1
    return sent


# --- Endpoints ---

@router.get("/payrates")
async def payrates(_user=Depends(current_user)):
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute("SELECT * FROM payrates ORDER BY role")).fetchall()
        return [
            {
                **dict(row),
                "min_rate": int(row["min_rate"] or row["base_rate"]),
                "max_rate": int(row["max_rate"] or row["base_rate"]),
            }
            for row in rows
        ]
    finally:
        await connection.close()


@router.put("/payrates/{role}")
async def update_payrate(
    role: Literal["TL", "TS", "TL+TS"], payload: PayrateUpdate, user=Depends(admin_user)
):
    connection = await dashboard_db()
    try:
        old = await (await connection.execute("SELECT * FROM payrates WHERE role=?", (role,))).fetchone()
        min_rate = payload.min_rate if payload.min_rate is not None else payload.base_rate
        if min_rate is None:
            raise HTTPException(status_code=422, detail="Rate minimum wajib diisi.")
        max_rate = payload.max_rate
        if max_rate is None:
            old_data = dict(old) if old else {}
            max_rate = max(
                min_rate,
                int(old_data.get("max_rate") or DEFAULT_RATE_RANGES[role][1]),
            )
        if max_rate < min_rate:
            raise HTTPException(status_code=422, detail="Rate maksimum harus sama atau lebih besar dari minimum.")
        await connection.execute("""
            INSERT INTO payrates(role,base_rate,min_rate,max_rate,updated_at)
            VALUES(?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(role) DO UPDATE SET
                base_rate=excluded.base_rate,
                min_rate=excluded.min_rate,
                max_rate=excluded.max_rate,
                updated_at=CURRENT_TIMESTAMP
        """, (role, min_rate, min_rate, max_rate))
        await connection.commit()
    finally:
        await connection.close()
    panel_updated, notified = await asyncio.gather(
        update_discord_payrate_panel(),
        broadcast_payrate_to_staff(role, min_rate, max_rate),
    )
    result = {
        "role": role,
        "base_rate": min_rate,
        "min_rate": min_rate,
        "max_rate": max_rate,
        "panel_updated": panel_updated,
        "notified": notified,
    }
    await audit(
        user["id"],
        "payrate.update",
        "payrate",
        role,
        dict(old) if old else None,
        result,
    )
    return result

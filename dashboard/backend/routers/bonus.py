"""Bonus router — Performance bonuses and manual bonuses."""

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

import performance_bonus as bonus_service
from dashboard.backend.deps import admin_user, audit, dashboard_db, DEV_BYPASS
from enums import AssignmentStatus, PayoutStatus, BonusStatus
from dashboard.backend.helpers import discord_api, enrich_staff

router = APIRouter(prefix="/api", tags=["bonus"])


# --- Pydantic models ---

class BonusSettingsUpdate(BaseModel):
    quality_weight: int = Field(ge=0, le=100)
    speed_weight: int = Field(ge=0, le=100)
    consistency_weight: int = Field(ge=0, le=100)
    min_chapters: int = Field(ge=1, le=100)
    tier_1_score: int = Field(ge=0, le=100)
    tier_1_percent: int = Field(ge=0, le=100)
    tier_2_score: int = Field(ge=0, le=100)
    tier_2_percent: int = Field(ge=0, le=100)
    tier_3_score: int = Field(ge=0, le=100)
    tier_3_percent: int = Field(ge=0, le=100)
    max_amount: int = Field(ge=0, le=10_000_000)


class BonusRunRequest(BaseModel):
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class BonusRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ManualBonusCreateRequest(BaseModel):
    staff_id: str = Field(min_length=1)
    amount: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=200)
    period: str | None = Field(default=None)

    @field_validator("staff_id", mode="before")
    @classmethod
    def coerce_staff_id(cls, v):
        return str(v)


# --- Helper ---

async def send_bonus_ticket_notice(bonus: dict) -> bool:
    if DEV_BYPASS:
        return True
    connection = await dashboard_db()
    try:
        row = await (await connection.execute("""SELECT ticket_channel_id FROM assignments
            WHERE CAST(staff_id AS TEXT)=? AND ticket_channel_id IS NOT NULL
            ORDER BY id DESC LIMIT 1""", (str(bonus["staff_id"]),))).fetchone()
    finally:
        await connection.close()
    if not row or not row["ticket_channel_id"]:
        return False
    payload = {
        "content": f"<@{bonus['staff_id']}>",
        "allowed_mentions": {"users": [str(bonus["staff_id"])]},
        "embeds": [{
            "title": "Bonus Performa Disetujui",
            "description": "Terima kasih atas kontribusi dan konsistensi kamu bulan ini.",
            "color": 3196747,
            "fields": [
                {"name": "Periode", "value": bonus["period"], "inline": True},
                {"name": "Skor", "value": f"{bonus['total_score']:.1f}/100", "inline": True},
                {"name": "Pencapaian", "value": bonus.get("tier") or "-", "inline": True},
                {"name": "Bonus", "value": f"Rp {int(bonus['proposed_amount']):,.0f}".replace(",", "."), "inline": True},
                {"name": "Pembayaran", "value": "Masuk ke invoice gajian berikutnya.", "inline": False},
            ],
            "footer": {"text": "Rincian performa ini bersifat privat."},
        }],
    }
    return bool(await discord_api("POST", f"/channels/{row['ticket_channel_id']}/messages", payload))


# --- Performance bonus endpoints ---

@router.get("/performance-bonuses/settings")
async def performance_bonus_settings(_user=Depends(admin_user)):
    return await bonus_service.get_settings()


@router.put("/performance-bonuses/settings")
async def update_performance_bonus_settings(payload: BonusSettingsUpdate, user=Depends(admin_user)):
    before = await bonus_service.get_settings()
    try:
        result = await bonus_service.update_settings(payload.model_dump(), user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await audit(user["id"], "performance_bonus.settings", "performance_bonus_settings", "1", before, result)
    return result


@router.get("/performance-bonuses")
async def performance_bonus_list(
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    status: str | None = Query(default=None), _user=Depends(admin_user),
):
    return await enrich_staff(await bonus_service.list_bonuses(period, status))


@router.post("/performance-bonuses/run")
async def run_performance_bonus(payload: BonusRunRequest, user=Depends(admin_user)):
    try:
        rows = await bonus_service.evaluate_period(payload.period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Periode tidak valid.") from exc
    await audit(user["id"], "performance_bonus.evaluate", "performance_bonus", payload.period or bonus_service.previous_period(),
                None, {"count": len(rows)})
    return {"count": len(rows), "period": payload.period or bonus_service.previous_period()}


@router.post("/performance-bonuses/{bonus_id}/approve")
async def approve_performance_bonus(bonus_id: int, user=Depends(admin_user)):
    try:
        result = await bonus_service.review_bonus(bonus_id, "approve", user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    notified = await send_bonus_ticket_notice(result)
    await audit(user["id"], "performance_bonus.approve", "performance_bonus", bonus_id,
                {"status": "pending"}, {"status": "approved", "amount": result["proposed_amount"], "notified": notified})
    return {**result, "notified": notified}


@router.post("/performance-bonuses/{bonus_id}/reject")
async def reject_performance_bonus(bonus_id: int, payload: BonusRejectRequest, user=Depends(admin_user)):
    try:
        result = await bonus_service.review_bonus(bonus_id, "reject", user["id"], payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await audit(user["id"], "performance_bonus.reject", "performance_bonus", bonus_id,
                {"status": "pending"}, {"status": "rejected", "reason": payload.reason})
    return result


# --- Manual bonus endpoints ---

@router.get("/manual-bonuses")
async def list_manual_bonuses_route(
    staff_id: str | None = Query(default=None),
    period: str | None = Query(default=None),
    status: str | None = Query(default=None),
    _user=Depends(admin_user),
):
    clean_staff = staff_id.strip() if staff_id and staff_id.strip() else None
    clean_period = period.strip() if period and re.match(r"^\d{4}-\d{2}$", period.strip()) else None
    clean_status = status.strip() if status and status.strip() else None
    return await enrich_staff(await bonus_service.list_manual_bonuses(clean_staff, clean_period, clean_status))


@router.post("/manual-bonuses")
async def create_manual_bonus_route(payload: ManualBonusCreateRequest, user=Depends(admin_user)):
    clean_period = payload.period.strip() if payload.period and payload.period.strip() else None
    if clean_period and not re.match(r"^\d{4}-\d{2}$", clean_period):
        clean_period = None
    try:
        result = await bonus_service.create_manual_bonus(
            staff_id=payload.staff_id.strip(),
            amount=payload.amount,
            reason=payload.reason.strip(),
            created_by=user["id"],
            period=clean_period,
        )
        connection = await dashboard_db()
        try:
            row = await (await connection.execute("""SELECT ticket_channel_id FROM assignments
                WHERE staff_id=? AND ticket_channel_id IS NOT NULL ORDER BY id DESC LIMIT 1""", (payload.staff_id.strip(),))).fetchone()
            if row and row["ticket_channel_id"]:
                message = {
                    "embeds": [{
                        "title": "🎉 BONUS TAMBAHAN DITERIMA!",
                        "description": f"Kamu mendapatkan tambahan bonus manual yang akan ditambahkan ke saldo invoice gaji mu berikutnya.\n\n**Alasan:** {payload.reason.strip()}\n**Jumlah Bonus:** Rp {payload.amount:,}",
                        "color": 0x57F287
                    }]
                }
                await discord_api("POST", f"/channels/{row['ticket_channel_id']}/messages", message)
        finally:
            await connection.close()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await audit(
        user["id"], "manual_bonus.create", "manual_bonus", str(result["id"]),
        None, result
    )
    return result


@router.post("/manual-bonuses/{bonus_id}/cancel")
async def cancel_manual_bonus_route(bonus_id: int, user=Depends(admin_user)):
    try:
        result = await bonus_service.cancel_manual_bonus(bonus_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await audit(
        user["id"], "manual_bonus.cancel", "manual_bonus", str(bonus_id),
        {"status": "approved"}, {"status": "cancelled"}
    )
    return result

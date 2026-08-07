"""Notification preferences router."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import database as staff_db
from dashboard.backend.deps import admin_user, current_user
from dashboard.backend.helpers import discord_api

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotifPref(BaseModel):
    notif_type: str
    channel: str = "ticket"
    enabled: bool = True
    reminder_hours: int = 24


class BulkPrefs(BaseModel):
    preferences: list[NotifPref]


@router.get("/preferences")
async def get_preferences(user=Depends(current_user)):
    staff_id = int(user["id"])
    prefs = await staff_db.get_notification_preferences(staff_id)
    return {
        "staff_id": str(staff_id),
        "types": list(staff_db.NOTIF_TYPES),
        "channels": list(staff_db.NOTIF_CHANNELS),
        "preferences": prefs,
    }


@router.put("/preferences")
async def update_preferences(payload: BulkPrefs, user=Depends(current_user)):
    staff_id = int(user["id"])
    prefs = [p.model_dump() for p in payload.preferences]
    await staff_db.bulk_set_preferences(staff_id, prefs)
    return {"ok": True}


@router.get("/preferences/{staff_id}")
async def get_staff_preferences(staff_id: int, user=Depends(admin_user)):
    prefs = await staff_db.get_notification_preferences(staff_id)
    return {
        "staff_id": str(staff_id),
        "preferences": prefs,
    }

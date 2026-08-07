"""Operations router — System status, event resolution, and notification outbox."""

import time

from fastapi import APIRouter, Depends, HTTPException

import operations
from dashboard.backend.deps import admin_user, audit, _staff_cache
from dashboard.backend.helpers import enrich_staff

router = APIRouter(prefix="/api", tags=["operations"])


@router.get("/operations")
async def operations_status(_user=Depends(admin_user)):
    snapshot = await operations.operations_snapshot()
    snapshot["staff_cache"] = {
        "count": len(_staff_cache["items"]),
        "updated_at": _staff_cache["updated_at"],
        "ttl_seconds": max(0, int(_staff_cache["expires_at"] - time.monotonic())),
    }
    return snapshot


@router.post("/operations/events/{event_id}/resolve")
async def resolve_operation_event(event_id: int, user=Depends(admin_user)):
    if not await operations.resolve_event(event_id, user["id"]):
        raise HTTPException(status_code=404, detail="Error aktif tidak ditemukan.")
    await audit(user["id"], "operation.resolve", "system_event", event_id)
    return {"ok": True}


@router.post("/operations/outbox/{item_id}/retry")
async def retry_outbox_item(item_id: int, user=Depends(admin_user)):
    if not await operations.retry_notification(item_id):
        raise HTTPException(status_code=409, detail="Notifikasi tidak berstatus gagal.")
    await audit(user["id"], "notification.retry", "outbox", item_id)
    return {"ok": True}

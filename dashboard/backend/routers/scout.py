"""Scout router — Project scout search, details, and decisions."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import project_scout as scout_service
from dashboard.backend.deps import admin_user, audit

router = APIRouter(prefix="/api/scout", tags=["scout"])


# --- Pydantic models ---

class ScoutSearchRequest(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    raw_source: Literal["all", "asura", "omega", "doujiva", "evascan", "thunder"] = "all"
    force: bool = False


class ScoutDecisionRequest(BaseModel):
    action: Literal["candidate", "adopt", "available", "ignore", "ambiguous"]
    notes: str = Field(default="", max_length=1000)


# --- Endpoints ---

@router.get("")
async def scout_titles(
    status: str = "", search: str = "", page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50), user=Depends(admin_user),
):
    allowed = {
        "", "untranslated", "lagging", "available", "ambiguous", "ryukomik_project",
        "candidate", "adopted", "ignored", "active_indonesia",
    }
    if status not in allowed:
        raise HTTPException(status_code=422, detail="Status Project Scout tidak dikenal.")
    return await scout_service.list_scout_titles(status, search.strip(), page, page_size)


@router.post("/search")
async def scout_search(payload: ScoutSearchRequest, user=Depends(admin_user)):
    try:
        result = await scout_service.scan_title(
            payload.title, payload.raw_source, force=payload.force,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    await audit(user["id"], "scout.search", "scout_title", result["id"], after={
        "title": payload.title, "raw_source": payload.raw_source,
        "status": result["scout_status"], "confidence": result["confidence"],
        "cached": result.get("cached", False),
    })
    return result


@router.get("/{scout_id}")
async def scout_detail(scout_id: int, user=Depends(admin_user)):
    result = await scout_service.get_scout_title(scout_id)
    if not result:
        raise HTTPException(status_code=404, detail="Kandidat Project Scout tidak ditemukan.")
    return result


@router.post("/{scout_id}/decision")
async def scout_decision(scout_id: int, payload: ScoutDecisionRequest, user=Depends(admin_user)):
    try:
        result = await scout_service.decide(scout_id, int(user["id"]), payload.action, payload.notes.strip())
    except ValueError as error:
        raise HTTPException(status_code=404 if "ditemukan" in str(error) else 422, detail=str(error))
    await audit(user["id"], f"scout.{payload.action}", "scout_title", scout_id, after={
        "status": result["scout_status"], "notes": payload.notes.strip() or None,
    })
    return result

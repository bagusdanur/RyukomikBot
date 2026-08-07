"""Payouts router — list, detail, QRIS, PDF, pay, reject, resend invoice."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import payment_service as payout_service
from dashboard.backend.deps import (
    admin_user, audit, dashboard_db, normalize_paging, page_payload,
)
from enums import AssignmentStatus, PayoutStatus, BonusStatus
from invoice_pdf import render_paid_invoice

router = APIRouter(prefix="/api/payouts", tags=["payouts"])


# ---------------------------------------------------------------------------
# Local helpers (late-imported from app.py to avoid circular deps)
# ---------------------------------------------------------------------------

async def _enrich_staff(rows):
    from dashboard.backend.helpers import enrich_staff
    return await enrich_staff(rows)


async def _send_paid_invoice_pdf(payout_id: int, admin_name: str):
    from dashboard.backend.helpers import send_paid_invoice_pdf
    return await send_paid_invoice_pdf(payout_id, admin_name)


async def _send_payout_ticket_notice(staff_id: int, title: str, description: str, success: bool):
    from dashboard.backend.helpers import send_payout_ticket_notice
    return await send_payout_ticket_notice(staff_id, title, description, success)


# ---------------------------------------------------------------------------
# Pydantic models (mirrors app.py)
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field


class PayoutRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class PayoutPayConfirmRequest(BaseModel):
    amount: int = Field(gt=0)
    destination_last4: str = Field(pattern=r"^[0-9A-Za-z]{4}$")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def payout_requests(
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    paginated: bool = Query(default=False),
    _user=Depends(admin_user),
):
    page, page_size, paginated = normalize_paging(page, page_size, paginated)
    if status and status not in {"awaiting_method", "issued", "paid", "rejected", "cancelled"}:
        raise HTTPException(status_code=422, detail="Status pencairan tidak valid.")
    rows = await _enrich_staff(await payout_service.list_payouts(status))
    if paginated:
        start = (page - 1) * page_size
        return page_payload(rows[start:start + page_size], page, page_size, len(rows))
    return rows


@router.get("/{payout_id}")
async def payout_request_detail(payout_id: int, _user=Depends(admin_user)):
    detail = await payout_service.payout_detail(payout_id, include_sensitive=True)
    if not detail:
        raise HTTPException(status_code=404, detail="Permintaan gaji tidak ditemukan.")
    return (await _enrich_staff([detail]))[0]


@router.get("/{payout_id}/qris")
async def payout_qris(payout_id: int, _user=Depends(admin_user)):
    detail = await payout_service.payout_detail(payout_id, include_sensitive=True)
    object_key = detail and detail["method"].get("qris_object_key")
    if not object_key:
        raise HTTPException(status_code=404, detail="QRIS tidak tersedia.")
    try:
        url = await payout_service.qris_download_url(object_key, 600)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))
    return {"download_url": url, "expires_in": 600}


@router.get("/{payout_id}/pdf")
async def payout_invoice_pdf(payout_id: int, _user=Depends(admin_user)):
    detail = await payout_service.payout_detail(payout_id, include_sensitive=True)
    if not detail:
        raise HTTPException(status_code=404, detail="Permintaan gaji tidak ditemukan.")
    detail = (await _enrich_staff([detail]))[0]
    pdf = render_paid_invoice(detail, staff_name=detail.get("staff_name"))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{detail["invoice_number"]}.pdf"'},
    )


@router.post("/{payout_id}/resend-invoice")
async def resend_payout_invoice(payout_id: int, user=Depends(admin_user)):
    detail = await payout_service.payout_detail(payout_id)
    if not detail or detail["status"] != "paid":
        raise HTTPException(status_code=409, detail="Invoice hanya dapat dikirim untuk pembayaran lunas.")
    sent, error = await _send_paid_invoice_pdf(payout_id, user["username"])
    await audit(
        user["id"], "payout.invoice_resend", "payout", payout_id,
        after={"sent": sent, "error": error},
    )
    if not sent:
        raise HTTPException(status_code=502, detail=f"Invoice gagal dikirim: {error}")
    return {"ok": True}


@router.post("/{payout_id}/pay")
async def pay_payout_request(
    payout_id: int,
    payload: PayoutPayConfirmRequest,
    user=Depends(admin_user),
):
    before = await payout_service.payout_detail(payout_id)
    if not before:
        raise HTTPException(status_code=404, detail="Permintaan gaji tidak ditemukan.")
    sensitive = await payout_service.payout_detail(payout_id, include_sensitive=True)
    destination = (
        sensitive["method"].get("account_number")
        or sensitive["method"].get("masked_account")
        or "QRIS"
    )
    expected_last4 = "".join(char for char in str(destination) if char.isalnum())[-4:]
    if payload.amount != int(before["total_amount"]) or payload.destination_last4.casefold() != expected_last4.casefold():
        raise HTTPException(
            status_code=422,
            detail="Nominal atau 4 karakter terakhir tujuan pembayaran tidak cocok.",
        )
    try:
        payout = await payout_service.pay_payout(payout_id, int(user["id"]))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    await audit(user["id"], "payout.pay", "payout", payout_id,
                {"status": before["status"]}, {"status": "paid"})
    sent, error = await _send_paid_invoice_pdf(payout_id, user["username"])
    return {"ok": True, "invoice_sent": sent, "invoice_error": error}


@router.post("/{payout_id}/reject")
async def reject_payout_request(
    payout_id: int,
    payload: PayoutRejectRequest,
    user=Depends(admin_user),
):
    before = await payout_service.payout_detail(payout_id)
    if not before:
        raise HTTPException(status_code=404, detail="Permintaan gaji tidak ditemukan.")
    try:
        payout = await payout_service.reject_payout(payout_id, int(user["id"]), payload.reason)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    await audit(
        user["id"], "payout.reject", "payout", payout_id,
        {"status": before["status"]}, {"status": "rejected", "reason": payload.reason},
    )
    await _send_payout_ticket_notice(
        int(payout["staff_id"]), "Pengajuan Gaji Ditolak", payload.reason, False,
    )
    return {"ok": True}

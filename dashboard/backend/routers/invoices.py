"""Invoices router — CRUD, refresh, correction, pay, void."""

import secrets

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import payment_service as payout_service
import performance_bonus as bonus_service
from dashboard.backend.deps import admin_user, audit, dashboard_db
from enums import AssignmentStatus, PayoutStatus, BonusStatus

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


# ---------------------------------------------------------------------------
# Local helpers (extracted from app.py — _replace_invoice_items lives here)
# ---------------------------------------------------------------------------

async def _enrich_staff(rows):
    """Late-import to avoid circular dependency with app.py."""
    from dashboard.backend.helpers import enrich_staff
    return await enrich_staff(rows)


async def _send_paid_invoice_pdf(payout_id: int, admin_name: str):
    """Late-import to avoid circular dependency with app.py."""
    from dashboard.backend.helpers import send_paid_invoice_pdf
    return await send_paid_invoice_pdf(payout_id, admin_name)


async def _replace_invoice_items(connection, invoice, items, actor_id: int):
    """Re-assign items to an issued invoice (same logic as app.py L2687-2713)."""
    if invoice["status"] != "issued":
        raise HTTPException(status_code=409, detail="Hanya invoice berstatus issued yang dapat direvisi.")
    bonus_total = int((await (await connection.execute(
        "SELECT COALESCE(SUM(amount),0) total FROM dashboard_invoice_bonus_items WHERE invoice_id=?",
        (invoice["id"],))).fetchone())["total"])
    manual_bonus_total = int((await (await connection.execute(
        "SELECT COALESCE(SUM(amount),0) total FROM dashboard_invoice_manual_bonus_items WHERE invoice_id=?",
        (invoice["id"],))).fetchone())["total"])
    total_bonuses = bonus_total + manual_bonus_total
    if not items and not total_bonuses:
        raise HTTPException(status_code=422, detail="Tidak ada tugas approved atau bonus yang dapat dimasukkan ke invoice.")
    old_ids = [row["assignment_id"] for row in await (await connection.execute(
        "SELECT assignment_id FROM dashboard_invoice_items WHERE invoice_id=?", (invoice["id"],)
    )).fetchall()]
    await connection.execute("DELETE FROM dashboard_assignment_billing WHERE invoice_id=?", (invoice["id"],))
    await connection.execute("DELETE FROM dashboard_invoice_items WHERE invoice_id=?", (invoice["id"],))
    try:
        await connection.executemany(
            """INSERT INTO dashboard_invoice_items
            (invoice_id,assignment_id,manga,chapter,role,amount,assigned_at,approved_at,chapter_count,rate_per_chapter)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [(invoice["id"], item["id"], item["manga"], item["chapter"], item["role"],
              item["final_rate"], item["assigned_at"], item["approved_at"],
              item["chapter_count"] or 1, item["rate_per_chapter"] or item["final_rate"]) for item in items],
        )
        await connection.executemany(
            "INSERT INTO dashboard_assignment_billing(assignment_id,invoice_id) VALUES(?,?)",
            [(item["id"], invoice["id"]) for item in items],
        )
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Salah satu tugas sudah ditagihkan pada invoice lain.")
    await connection.execute(
        """UPDATE dashboard_invoices SET chapter_count=?,total_amount=?,
        revised_at=CURRENT_TIMESTAMP,revised_by=? WHERE id=?""",
        (sum(item["chapter_count"] or 1 for item in items),
         sum(item["final_rate"] for item in items) + total_bonuses, actor_id, invoice["id"]),
    )
    return old_ids


# ---------------------------------------------------------------------------
# Pydantic model (mirrors app.py InvoiceCreate)
# ---------------------------------------------------------------------------

class InvoiceCreate(BaseModel):
    staff_id: str | int
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def invoices(
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    _user=Depends(admin_user),
):
    connection = await dashboard_db()
    try:
        where, params = (" WHERE period=?", [period]) if period else ("", [])
        rows = await (await connection.execute(
            f"SELECT * FROM dashboard_invoices{where} ORDER BY issued_at DESC LIMIT 200", params,
        )).fetchall()
        return await _enrich_staff(rows)
    finally:
        await connection.close()


@router.get("/{invoice_id}")
async def invoice_detail(invoice_id: int, _user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        invoice = await (await connection.execute(
            "SELECT * FROM dashboard_invoices WHERE id=?", (invoice_id,),
        )).fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")
        items = await (await connection.execute("""
            SELECT assignment_id,manga,chapter,role,amount,assigned_at,approved_at,
                   chapter_count,rate_per_chapter
            FROM dashboard_invoice_items WHERE invoice_id=? ORDER BY assignment_id
        """, (invoice_id,))).fetchall()
        bonus_items = await bonus_service.invoice_bonus_items(connection, invoice_id)
        manual_bonus_items = await bonus_service.invoice_manual_bonus_items(connection, invoice_id)
        if not items:
            status_clause = "paid_period=?" if invoice["status"] == "paid" else "status='approved'"
            params = [invoice["staff_id"]]
            if invoice["status"] == "paid":
                params.append(invoice["period"])
            items = await (await connection.execute(f"""
                SELECT id assignment_id,manga,chapter,role,final_rate amount,assigned_at,approved_at,
                       COALESCE(chapter_count,1) chapter_count,COALESCE(rate_per_chapter,final_rate) rate_per_chapter
                FROM assignments WHERE staff_id=? AND {status_clause} ORDER BY id
            """, params)).fetchall()
        result = (await _enrich_staff([invoice]))[0]
        result["items"] = [dict(item) for item in items] + [{
            "assignment_id": None, "item_type": "performance_bonus", "manga": "Bonus Performa",
            "chapter": item["period"], "role": "BONUS", "amount": item["amount"],
            "chapter_count": 0, "rate_per_chapter": item["amount"], "assigned_at": None,
            "approved_at": None, "score": item.get("total_score"), "percentage": item.get("percentage"),
        } for item in bonus_items] + [{
            "assignment_id": None, "item_type": "manual_bonus", "manga": f"Bonus Manual: {item['reason']}",
            "chapter": item.get("period") or "-", "role": "BONUS", "amount": item["amount"],
            "chapter_count": 0, "rate_per_chapter": item["amount"], "assigned_at": None,
            "approved_at": None, "score": None, "percentage": None,
        } for item in manual_bonus_items]
        dates = [item["assigned_at"] for item in items if item["assigned_at"]]
        approved = [item["approved_at"] for item in items if item["approved_at"]]
        result["work_started_at"] = min(dates) if dates else None
        result["work_ended_at"] = max(approved) if approved else None
        return result
    finally:
        await connection.close()


@router.post("", status_code=201)
async def create_invoice(payload: InvoiceCreate, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        period = payload.period or datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m")
        items = await (await connection.execute("""
            SELECT id,manga,chapter,role,final_rate,assigned_at,approved_at,
                   COALESCE(chapter_count,1) chapter_count,COALESCE(rate_per_chapter,final_rate) rate_per_chapter
            FROM assignments a WHERE staff_id=? AND status='approved'
              AND NOT EXISTS (SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id)
            ORDER BY id
        """, (payload.staff_id,))).fetchall()
        bonus_rows = await (await connection.execute(
            """SELECT id FROM performance_bonuses
            WHERE staff_id=? AND status='approved' AND invoice_id IS NULL AND proposed_amount>0""",
            (str(payload.staff_id),),
        )).fetchall()
        manual_rows = await (await connection.execute(
            """SELECT id FROM manual_bonuses
            WHERE staff_id=? AND status='approved' AND invoice_id IS NULL AND amount>0""",
            (str(payload.staff_id),),
        )).fetchall()
        if not items and not bonus_rows and not manual_rows:
            raise HTTPException(status_code=422, detail="Tidak ada tugas approved atau bonus yang belum dibayar untuk staff ini.")
        chapter_count = sum(item["chapter_count"] or 1 for item in items)
        total_amount = sum(item["final_rate"] for item in items)
        invoice_number = f"RYU-{period.replace('-', '')}-{payload.staff_id}-{secrets.token_hex(2).upper()}"
        try:
            cursor = await connection.execute("""
                INSERT INTO dashboard_invoices
                    (invoice_number,staff_id,period,chapter_count,total_amount,status,issued_by)
                VALUES(?,?,?,?,?,'issued',?)
            """, (invoice_number, payload.staff_id, period, chapter_count, total_amount, user["id"]))
            invoice_id = cursor.lastrowid
            await connection.executemany("""
                INSERT INTO dashboard_invoice_items
                    (invoice_id,assignment_id,manga,chapter,role,amount,assigned_at,approved_at,chapter_count,rate_per_chapter)
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, [(
                invoice_id, item["id"], item["manga"], item["chapter"], item["role"],
                item["final_rate"], item["assigned_at"], item["approved_at"],
                item["chapter_count"] or 1, item["rate_per_chapter"] or item["final_rate"],
            ) for item in items])
            await connection.executemany(
                "INSERT INTO dashboard_assignment_billing(assignment_id,invoice_id) VALUES(?,?)",
                [(item["id"], invoice_id) for item in items],
            )
            bonus_total = await bonus_service.attach_approved_to_invoice(connection, invoice_id, payload.staff_id)
            manual_bonus_total = await bonus_service.attach_manual_to_invoice(connection, invoice_id, payload.staff_id)
            total_bonus = (bonus_total or 0) + (manual_bonus_total or 0)
            if total_bonus:
                total_amount += total_bonus
                await connection.execute("UPDATE dashboard_invoices SET total_amount=? WHERE id=?", (total_amount, invoice_id))
            await connection.commit()
        except aiosqlite.IntegrityError:
            await connection.rollback()
            raise HTTPException(status_code=409, detail="Salah satu tugas sudah masuk invoice lain. Muat ulang data.")
    finally:
        await connection.close()
    # Invoice manual must follow the exact same payment queue as scheduled and
    # instant payouts.  Without this, an issued invoice exists but has no
    # actionable transfer entry on the Permintaan Gaji page.
    try:
        payout_id = await payout_service.ensure_payout_for_invoice(invoice_id)
    except Exception as error:
        # The invoice has already been committed.  Report an actionable error
        # rather than silently leaving it outside the transfer queue.
        raise HTTPException(
            status_code=500,
            detail="Invoice berhasil dibuat, tetapi gagal masuk antrean transfer. Coba muat ulang atau hubungi administrator.",
        ) from error
    await audit(user["id"], "invoice.create", "invoice", invoice_id, after={"invoice_number": invoice_number})
    return {"id": invoice_id, "invoice_number": invoice_number, "payout_id": payout_id}


@router.post("/{invoice_id}/refresh")
async def refresh_invoice(invoice_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        invoice = await (await connection.execute(
            "SELECT * FROM dashboard_invoices WHERE id=?", (invoice_id,),
        )).fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")
        items = await (await connection.execute("""
            SELECT a.id,a.manga,a.chapter,a.role,a.final_rate,a.assigned_at,a.approved_at,
                   COALESCE(a.chapter_count,1) chapter_count,COALESCE(a.rate_per_chapter,a.final_rate) rate_per_chapter
            FROM assignments a WHERE a.staff_id=? AND a.status='approved'
              AND (NOT EXISTS (SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id)
                   OR EXISTS (SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id AND b.invoice_id=?))
            ORDER BY a.id
        """, (invoice["staff_id"], invoice_id))).fetchall()
        before_items = await _replace_invoice_items(connection, invoice, items, user["id"])
        await connection.commit()
        after = {
            "chapter_count": sum(item["chapter_count"] or 1 for item in items),
            "total_amount": sum(item["final_rate"] for item in items),
            "assignment_ids": [item["id"] for item in items],
        }
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()
    await audit(user["id"], "invoice.refresh", "invoice", invoice_id, {"assignment_ids": before_items}, after)
    return {"ok": True, **after}


@router.post("/{invoice_id}/correction", status_code=201)
async def create_correction_invoice(invoice_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        parent = await (await connection.execute(
            "SELECT * FROM dashboard_invoices WHERE id=?", (invoice_id,),
        )).fetchone()
        if not parent or parent["status"] != "paid":
            raise HTTPException(status_code=409, detail="Invoice koreksi hanya dapat dibuat dari invoice yang sudah lunas.")
        items = await (await connection.execute("""
            SELECT a.id,a.manga,a.chapter,a.role,a.final_rate,a.assigned_at,a.approved_at,
                   COALESCE(a.chapter_count,1) chapter_count,COALESCE(a.rate_per_chapter,a.final_rate) rate_per_chapter
            FROM assignments a WHERE a.staff_id=? AND a.status='approved'
              AND NOT EXISTS (SELECT 1 FROM dashboard_assignment_billing b WHERE b.assignment_id=a.id) ORDER BY a.id
        """, (parent["staff_id"],))).fetchall()
        if not items:
            raise HTTPException(status_code=422, detail="Tidak ada tugas terlambat yang belum ditagihkan.")
        count = (await (await connection.execute(
            "SELECT COUNT(*) n FROM dashboard_invoices WHERE parent_invoice_id=?", (invoice_id,),
        )).fetchone())["n"] + 1
        number = f"{parent['invoice_number']}-C{count:02d}"
        cursor = await connection.execute("""
            INSERT INTO dashboard_invoices
                (invoice_number,staff_id,period,chapter_count,total_amount,status,issued_by,invoice_type,parent_invoice_id)
                VALUES(?,?,?,?,?,'issued',?,'correction',?)
        """, (
            number, parent["staff_id"], parent["period"],
            sum(i["chapter_count"] or 1 for i in items), sum(i["final_rate"] for i in items),
            user["id"], invoice_id,
        ))
        correction_id = cursor.lastrowid
        await connection.executemany("""
            INSERT INTO dashboard_invoice_items
                (invoice_id,assignment_id,manga,chapter,role,amount,assigned_at,approved_at,chapter_count,rate_per_chapter)
                VALUES(?,?,?,?,?,?,?,?,?,?)
        """, [
            (correction_id, i["id"], i["manga"], i["chapter"], i["role"], i["final_rate"],
             i["assigned_at"], i["approved_at"], i["chapter_count"] or 1, i["rate_per_chapter"] or i["final_rate"])
            for i in items
        ])
        await connection.executemany(
            "INSERT INTO dashboard_assignment_billing(assignment_id,invoice_id) VALUES(?,?)",
            [(i["id"], correction_id) for i in items],
        )
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()
    await audit(user["id"], "invoice.correction", "invoice", correction_id,
                after={"parent_invoice_id": invoice_id, "invoice_number": number})
    return {"id": correction_id, "invoice_number": number}


@router.post("/{invoice_id}/pay")
async def pay_invoice(invoice_id: int, user=Depends(admin_user)):
    try:
        payout_id = await payout_service.ensure_payout_for_invoice(invoice_id)
        before = await payout_service.payout_detail(payout_id)
        if before["status"] == "awaiting_method":
            raise HTTPException(
                status_code=409,
                detail="Staff belum memiliki metode pembayaran utama. Invoice belum dapat dibayar.",
            )
        await payout_service.pay_payout(payout_id, int(user["id"]))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    await audit(user["id"], "invoice.pay", "invoice", invoice_id,
                before={"status": "issued"}, after={"status": "paid"})
    sent, error = await _send_paid_invoice_pdf(payout_id, user["username"])
    return {"ok": True, "invoice_sent": sent, "invoice_error": error}


@router.delete("/{invoice_id}")
async def delete_invoice(invoice_id: int, user=Depends(admin_user)):
    connection = await dashboard_db()
    try:
        invoice = await (await connection.execute(
            "SELECT * FROM dashboard_invoices WHERE id=?", (invoice_id,),
        )).fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")
        if invoice["status"] == "paid":
            raise HTTPException(status_code=409, detail="Invoice yang sudah lunas tidak dapat dihapus.")
        if invoice["status"] == "void":
            raise HTTPException(status_code=409, detail="Invoice sudah dibatalkan.")
        await connection.execute("DELETE FROM dashboard_assignment_billing WHERE invoice_id=?", (invoice_id,))
        await bonus_service.release_invoice(connection, invoice_id)
        await bonus_service.release_manual_invoice(connection, invoice_id)
        await connection.execute(
            "UPDATE dashboard_invoices SET status='void',voided_at=CURRENT_TIMESTAMP,voided_by=? WHERE id=?",
            (user["id"], invoice_id),
        )
        await connection.commit()
    finally:
        await connection.close()
    await audit(user["id"], "invoice.void", "invoice", invoice_id,
                before=dict(invoice), after={"status": "void"})
    return {"ok": True, "status": "void"}

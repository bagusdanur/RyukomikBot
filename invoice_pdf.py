"""Generate the same paid-invoice PDF for Discord and the admin dashboard."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def currency(value):
    return f"Rp {int(value or 0):,}".replace(",", ".")


def masked_method(method):
    if not method or not method.get("method_type"):
        return "Belum ditentukan"
    if method["method_type"] == "qris":
        return f"QRIS - {method.get('account_name') or '-'}"
    number = str(method.get("account_number") or "")
    return f"{method.get('provider') or '-'} - ****{number[-4:] if number else '----'}"


def render_paid_invoice(detail, staff_name=None, admin_name=None):
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=detail["invoice_number"], author="Ryukomik Staff Management",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="InvoiceRight", parent=styles["Normal"], alignment=TA_RIGHT, leading=16))
    story = [
        Table([[
            Paragraph("<b>RYUKOMIK</b><br/><font color='#68748a'>Staff Payment Invoice</font>", styles["Title"]),
            Paragraph(
                f"<b>{detail['invoice_number']}</b><br/><font color='#087443'>LUNAS</font>",
                styles["InvoiceRight"],
            ),
        ]], colWidths=[110 * mm, 52 * mm]),
        Spacer(1, 8 * mm),
    ]
    info = [
        ["Penerima", staff_name or detail.get("staff_name") or f"Staff {detail['staff_id']}"],
        ["Periode", detail.get("period") or "-"],
        ["Rentang kerja", f"{detail.get('cutoff_start') or '-'} s.d. {detail.get('cutoff_end') or '-'}"],
        ["Tujuan pembayaran", masked_method(detail.get("method"))],
        ["Dibayar pada", detail.get("processed_at") or detail.get("paid_at") or "-"],
        ["Dikonfirmasi oleh", admin_name or str(detail.get("processed_by") or "-")],
    ]
    info_table = Table(info, colWidths=[43 * mm, 119 * mm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f3f8")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#566176")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9deea")),
        ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([info_table, Spacer(1, 8 * mm), Paragraph("<b>Rincian Pekerjaan</b>", styles["Heading3"])])
    rows = [["No.", "Judul", "Chapter", "Role", "Rate/ch", "Jml.", "Bayaran"]]
    for index, item in enumerate(detail.get("items") or [], 1):
        rows.append([
            index, Paragraph(str(item.get("manga") or "-"), styles["BodyText"]),
            str(item.get("chapter") or "-"), str(item.get("role") or "-"),
            currency(item.get("rate_per_chapter") or item.get("amount")),
            int(item.get("chapter_count") or 1), currency(item.get("amount")),
        ])
    table = Table(rows, repeatRows=1, colWidths=[9 * mm, 51 * mm, 21 * mm, 15 * mm, 23 * mm, 11 * mm, 32 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6574f7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d9deea")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fc")]),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([
        table, Spacer(1, 7 * mm),
        Table([["Jumlah chapter", int(detail.get("chapter_count") or 0)],
               ["TOTAL DIBAYAR", currency(detail.get("total_amount"))]],
              colWidths=[115 * mm, 47 * mm], style=[
                  ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                  ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                  ("FONTSIZE", (0, 1), (-1, 1), 13),
                  ("LINEABOVE", (0, 1), (-1, 1), 1.2, colors.HexColor("#6574f7")),
                  ("PADDING", (0, 0), (-1, -1), 7),
              ]),
        Spacer(1, 12 * mm),
        Paragraph(
            "Dokumen ini dibuat otomatis oleh Ryukomik Staff Management setelah administrator "
            "mengonfirmasi transfer.", styles["BodyText"],
        ),
    ])
    document.build(story)
    return output.getvalue()

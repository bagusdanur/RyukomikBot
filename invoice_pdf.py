"""Generate a professional paid salary slip for Discord and the dashboard."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


NAVY = colors.HexColor("#101827")
NAVY_SOFT = colors.HexColor("#182235")
INDIGO = colors.HexColor("#6674F4")
INDIGO_PALE = colors.HexColor("#EEF0FF")
GREEN = colors.HexColor("#159A6C")
GREEN_PALE = colors.HexColor("#EAF8F2")
TEXT = colors.HexColor("#172033")
MUTED = colors.HexColor("#68748A")
LINE = colors.HexColor("#DDE3ED")
SURFACE = colors.HexColor("#F5F7FB")
WHITE = colors.white


def currency(value):
    return f"Rp {int(value or 0):,}".replace(",", ".")


def masked_method(method):
    if not method or not method.get("method_type"):
        return "Belum ditentukan"
    if method["method_type"] == "qris":
        return f"QRIS - {method.get('account_name') or '-'}"
    number = str(method.get("account_number") or "")
    return f"{method.get('provider') or '-'} - ****{number[-4:] if number else '----'}"


def clean_date(value):
    if not value:
        return "-"
    return str(value).replace("T", " ")[:19]


class SalarySlipHeader(Flowable):
    """Dark branded header with a clear paid status."""

    def __init__(self, invoice_number, width=178 * mm, height=42 * mm):
        super().__init__()
        self.width = width
        self.height = height
        self.invoice_number = str(invoice_number)

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.roundRect(0, 0, self.width, self.height, 5 * mm, fill=1, stroke=0)

        canvas.setFillColor(INDIGO)
        canvas.circle(12 * mm, 27 * mm, 6 * mm, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawCentredString(12 * mm, 25.2 * mm, "R")

        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawString(22 * mm, 28 * mm, "RYUKOMIK")
        canvas.setFillColor(colors.HexColor("#AEB8CA"))
        canvas.setFont("Helvetica", 8.5)
        canvas.drawString(22 * mm, 21.5 * mm, "STAFF MANAGEMENT  /  PAYMENT DOCUMENT")

        canvas.setFillColor(GREEN)
        badge_width = 27 * mm
        canvas.roundRect(
            self.width - badge_width - 8 * mm,
            25 * mm,
            badge_width,
            9 * mm,
            4.5 * mm,
            fill=1,
            stroke=0,
        )
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawCentredString(self.width - badge_width / 2 - 8 * mm, 28 * mm, "LUNAS")

        canvas.setFillColor(colors.HexColor("#AEB8CA"))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(self.width - 8 * mm, 16 * mm, "NOMOR SLIP")
        canvas.setFillColor(WHITE)
        font_size = 9
        while stringWidth(self.invoice_number, "Helvetica-Bold", font_size) > 76 * mm and font_size > 6:
            font_size -= 0.5
        canvas.setFont("Helvetica-Bold", font_size)
        canvas.drawRightString(self.width - 8 * mm, 10 * mm, self.invoice_number)
        canvas.restoreState()


def _page_frame(canvas, document):
    canvas.saveState()
    width, _height = A4
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(16 * mm, 12 * mm, width - 16 * mm, 12 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(16 * mm, 7.5 * mm, "Dokumen resmi pembayaran staff Ryukomik")
    canvas.drawRightString(
        width - 16 * mm,
        7.5 * mm,
        f"Halaman {document.page}",
    )
    canvas.restoreState()


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="SlipSection",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=TEXT,
        spaceAfter=3 * mm,
    ))
    styles.add(ParagraphStyle(
        name="SlipBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=TEXT,
    ))
    styles.add(ParagraphStyle(
        name="SlipMuted",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        textColor=MUTED,
    ))
    styles.add(ParagraphStyle(
        name="SlipValue",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=TEXT,
    ))
    styles.add(ParagraphStyle(
        name="SlipName",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=TEXT,
    ))
    styles.add(ParagraphStyle(
        name="SlipNameRight",
        parent=styles["SlipName"],
        alignment=TA_RIGHT,
        fontSize=12,
        leading=15,
    ))
    styles.add(ParagraphStyle(
        name="SlipMutedRight",
        parent=styles["SlipMuted"],
        alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        name="SlipAmount",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_RIGHT,
        textColor=GREEN,
    ))
    styles.add(ParagraphStyle(
        name="SlipCenter",
        parent=styles["BodyText"],
        alignment=TA_CENTER,
        fontSize=8,
        leading=10,
        textColor=TEXT,
    ))
    styles.add(ParagraphStyle(
        name="SlipRight",
        parent=styles["BodyText"],
        alignment=TA_RIGHT,
        fontSize=8,
        leading=10,
        textColor=TEXT,
    ))
    styles.add(ParagraphStyle(
        name="SlipTable",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontSize=7.5,
        leading=10,
        textColor=TEXT,
    ))
    return styles


def _summary_card(label, value, styles, accent=False):
    return Table(
        [[Paragraph(label.upper(), styles["SlipMuted"])],
         [Paragraph(f"<b>{value}</b>", styles["SlipValue"])]],
        colWidths=[52 * mm],
        rowHeights=[7 * mm, 10 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREEN_PALE if accent else SURFACE),
            ("BOX", (0, 0), (-1, -1), 0.6, GREEN if accent else LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]),
    )


def render_paid_invoice(detail, staff_name=None, admin_name=None):
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=17 * mm,
        title=f"Slip Gaji {detail['invoice_number']}",
        author="Ryukomik Staff Management",
        subject="Bukti pembayaran gaji staff",
    )
    styles = _styles()
    receiver = staff_name or detail.get("staff_name") or f"Staff {detail['staff_id']}"
    processed_at = clean_date(detail.get("processed_at") or detail.get("paid_at"))
    work_range = f"{detail.get('cutoff_start') or '-'} s.d. {detail.get('cutoff_end') or '-'}"
    chapter_count = int(detail.get("chapter_count") or 0)

    story = [
        SalarySlipHeader(detail["invoice_number"]),
        Spacer(1, 6 * mm),
        Paragraph("SLIP GAJI STAFF", styles["SlipSection"]),
        Table(
            [[
                [
                    Paragraph("DIBAYARKAN KEPADA", styles["SlipMuted"]),
                    Paragraph(receiver, styles["SlipName"]),
                    Paragraph(f"Discord ID: {detail.get('staff_id') or '-'}", styles["SlipMuted"]),
                ],
                [
                    Paragraph("PERIODE KERJA", styles["SlipMutedRight"]),
                    Paragraph(str(detail.get("period") or "-"), styles["SlipNameRight"]),
                    Paragraph(work_range, styles["SlipMutedRight"]),
                ],
            ]],
            colWidths=[89 * mm, 89 * mm],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]),
        ),
        Spacer(1, 5 * mm),
        Table(
            [[
                _summary_card("Total Dibayar", currency(detail.get("total_amount")), styles, accent=True),
                _summary_card("Jumlah Chapter", f"{chapter_count} chapter", styles),
                _summary_card("Status", "LUNAS", styles),
            ]],
            colWidths=[59.3 * mm] * 3,
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
            ]),
        ),
        Spacer(1, 7 * mm),
        Paragraph("RINCIAN PEKERJAAN", styles["SlipSection"]),
    ]

    rows = [[
        Paragraph("<b>NO</b>", styles["SlipCenter"]),
        Paragraph("<b>JUDUL / CHAPTER</b>", styles["SlipTable"]),
        Paragraph("<b>ROLE</b>", styles["SlipCenter"]),
        Paragraph("<b>RATE / CH</b>", styles["SlipRight"]),
        Paragraph("<b>QTY</b>", styles["SlipCenter"]),
        Paragraph("<b>JUMLAH</b>", styles["SlipRight"]),
    ]]
    for index, item in enumerate(detail.get("items") or [], 1):
        title = str(item.get("manga") or "-")
        chapter = str(item.get("chapter") or "-")
        rows.append([
            Paragraph(str(index), styles["SlipCenter"]),
            Paragraph(f"<b>{title}</b><br/><font color='#68748A'>Chapter {chapter}</font>", styles["SlipTable"]),
            Paragraph(str(item.get("role") or "-"), styles["SlipCenter"]),
            Paragraph(currency(item.get("rate_per_chapter") or item.get("amount")), styles["SlipRight"]),
            Paragraph(str(int(item.get("chapter_count") or 1)), styles["SlipCenter"]),
            Paragraph(f"<b>{currency(item.get('amount'))}</b>", styles["SlipRight"]),
        ])

    work_table = Table(
        rows,
        repeatRows=1,
        colWidths=[10 * mm, 65 * mm, 18 * mm, 28 * mm, 13 * mm, 42 * mm],
    )
    work_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY_SOFT),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("LINEBELOW", (0, 0), (-1, 0), 1, INDIGO),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SURFACE]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("TOPPADDING", (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([work_table, Spacer(1, 7 * mm)])

    payment_info = Table(
        [[
            [
                Paragraph("METODE PEMBAYARAN", styles["SlipMuted"]),
                Paragraph(masked_method(detail.get("method")), styles["SlipValue"]),
                Spacer(1, 3 * mm),
                Paragraph("TANGGAL TRANSFER", styles["SlipMuted"]),
                Paragraph(processed_at, styles["SlipValue"]),
            ],
            [
                Paragraph("TOTAL PEMBAYARAN", styles["SlipMutedRight"]),
                Paragraph(currency(detail.get("total_amount")), styles["SlipAmount"]),
                Paragraph(f"{chapter_count} chapter telah dibayar", styles["SlipMutedRight"]),
            ],
        ]],
        colWidths=[89 * mm, 89 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREEN_PALE),
            ("BOX", (0, 0), (-1, -1), 0.8, GREEN),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 11),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
        ]),
    )
    story.extend([
        KeepTogether([
            payment_info,
            Spacer(1, 8 * mm),
            Table(
                [[
                    Paragraph(
                        "<font color='#68748A'>DIKONFIRMASI OLEH</font><br/>"
                        f"<b>{admin_name or str(detail.get('processed_by') or '-')}</b><br/>"
                        "<font color='#68748A'>Administrator Ryukomik</font>",
                        styles["SlipBody"],
                    ),
                    Paragraph(
                        "Dokumen ini dibuat otomatis setelah transfer dikonfirmasi. "
                        "Nomor tujuan pembayaran disamarkan untuk melindungi data staff.",
                        styles["SlipMuted"],
                    ),
                ]],
                colWidths=[75 * mm, 103 * mm],
                style=TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEABOVE", (0, 0), (-1, 0), 0.6, LINE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                ]),
            ),
        ]),
    ])

    document.build(story, onFirstPage=_page_frame, onLaterPages=_page_frame)
    return output.getvalue()

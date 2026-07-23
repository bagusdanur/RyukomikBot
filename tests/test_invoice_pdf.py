from invoice_pdf import clean_date, masked_method, render_paid_invoice


def sample_detail(item_count=2):
    items = [
        {
            "manga": f"Judul Manga Panjang untuk Pekerjaan {index}",
            "chapter": f"{index}-{index + 1}",
            "role": "TL+TS",
            "rate_per_chapter": 12000,
            "chapter_count": 2,
            "amount": 24000,
        }
        for index in range(1, item_count + 1)
    ]
    return {
        "invoice_number": "RYU-202607-880291779801403413-32IF",
        "staff_id": "880291779801403413",
        "staff_name": "Konata",
        "period": "2026-07",
        "cutoff_start": "2026-07-01",
        "cutoff_end": "2026-07-15",
        "chapter_count": item_count * 2,
        "total_amount": item_count * 24000,
        "processed_at": "2026-07-24 00:25:00",
        "processed_by": "Administrator",
        "method": {
            "method_type": "bank",
            "provider": "BCA",
            "account_name": "Konata",
            "account_number": "1234567890",
        },
        "items": items,
    }


def test_salary_slip_renders_professional_single_page_data():
    pdf = render_paid_invoice(sample_detail(), admin_name="Admin")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 3000


def test_salary_slip_handles_multi_page_work_table():
    pdf = render_paid_invoice(sample_detail(item_count=30), admin_name="Admin")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000


def test_payment_destination_remains_masked():
    assert masked_method(sample_detail()["method"]) == "BCA - ****7890"


def test_sqlite_utc_timestamp_is_rendered_as_jakarta_time():
    assert clean_date("2026-07-23 17:48:56") == "24 Juli 2026, 00:48 WIB"

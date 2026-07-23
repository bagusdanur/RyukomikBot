from views.ticket_views import build_completed_embed, build_revision_embed


ASSIGNMENT = {
    "id": 7,
    "manga": "Let's Do it After Work",
    "chapter": "1-3",
    "chapter_count": 3,
    "role": "TL+TS",
    "rate_per_chapter": 12000,
    "final_rate": 36000,
    "gdrive_link": "https://drive.google.com/drive/folders/example",
}


def fields(embed):
    return {field.name: field.value for field in embed.fields}


def test_completed_report_contains_work_and_drive_details():
    values = fields(build_completed_embed(ASSIGNMENT))
    assert values["Manga"] == "Let's Do it After Work"
    assert values["Jumlah Chapter"] == "3"
    assert values["Rate per Chapter"] == "Rp 12.000"
    assert values["Total Bayaran"] == "Rp 36.000"
    assert values["Hasil Google Drive"].startswith("https://drive.google.com/")


def test_revision_report_contains_notes_and_previous_result():
    values = fields(build_revision_embed(ASSIGNMENT, "Perbaiki halaman 11"))
    assert values["Catatan Administrator"] == "Perbaiki halaman 11"
    assert values["Hasil Sebelumnya"] == ASSIGNMENT["gdrive_link"]

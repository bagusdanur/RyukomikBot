"""Unit tests for Side-by-Side QC Viewer and Image Inspection Studio."""

import asyncio
import pytest
from dashboard.backend.routers.qc import (
    _clean_chapter,
    _parse_gdrive_folder_id,
    get_qc_details,
    qc_approve,
    qc_revise,
    QcReviseRequest,
    PageAnnotation,
)
import database as db_module
import project_scout as scout_service
import pair_workflow as pair_service


def test_qc_helpers():
    assert _clean_chapter("Chapter 4") == "4"
    assert _clean_chapter("Ch. 5.5") == "5.5"
    assert _clean_chapter("12") == "12"

    assert (
        _parse_gdrive_folder_id("https://drive.google.com/drive/folders/1ABC_xyz-123")
        == "1ABC_xyz-123"
    )
    assert (
        _parse_gdrive_folder_id("https://drive.google.com/open?id=FOLDER_ID_456")
        == "FOLDER_ID_456"
    )
    assert _parse_gdrive_folder_id("https://example.com/other") is None


def test_qc_details_and_actions(monkeypatch):
    async def _test():
        await db_module.setup_database()
        await scout_service.setup_scout_tables()
        await pair_service.setup_pair_tables()

        # Insert a sample assignment with submitted status
        db = await db_module.get_db()
        task_id = 0
        try:
            cursor = await db.execute(
                """INSERT INTO assignments (manga, chapter, staff_id, role, base_rate, final_rate, status, gdrive_link)
                   VALUES ('Let’s Do It After Work', '12', 1001, 'TS', 12000, 12000, 'submitted', 'https://drive.google.com/drive/folders/test-folder-123')"""
            )
            task_id = cursor.lastrowid
            await db.commit()
        finally:
            await db.close()

        # Mock RAW image resolver
        import dashboard.backend.routers.qc as qc_mod
        async def mock_raw_images(manga_title, chapter):
            return ["https://storage.ryukomik.my.id/page1.jpg", "https://storage.ryukomik.my.id/page2.jpg"], "omega"
        monkeypatch.setattr(qc_mod, "_resolve_raw_images", mock_raw_images)

        # 1. Fetch QC Details
        detail = await get_qc_details(task_id, user={"id": "1", "role": "admin"})
        assert detail["assignment"]["id"] == task_id
        assert detail["assignment"]["manga"] == "Let’s Do It After Work"
        assert detail["raw_pages"] == [
            "https://storage.ryukomik.my.id/page1.jpg",
            "https://storage.ryukomik.my.id/page2.jpg",
        ]
        assert detail["raw_source"] == "omega"
        assert detail["gdrive_folder_id"] == "test-folder-123"

        # 2. Request Revision with Page Annotations
        revise_payload = QcReviseRequest(
            notes="Perbaiki font dan typo ya.",
            page_notes=[
                PageAnnotation(page=1, comment="Typo di balon atas"),
                PageAnnotation(page=2, comment="Font SFX kurang rapi"),
            ],
        )

        # Mock discord notice
        async def mock_notice(*args, **kwargs):
            return True
        import dashboard.backend.routers.assignments as assign_mod
        monkeypatch.setattr(assign_mod, "send_ticket_review_notice", mock_notice)

        revise_res = await qc_revise(task_id, revise_payload, user={"id": "1", "role": "admin"})
        assert revise_res["ok"] is True

        # Check DB status changed to revision
        db2 = await db_module.get_db()
        try:
            row = await (await db2.execute("SELECT status FROM assignments WHERE id=?", (task_id,))).fetchone()
            assert row["status"] == "revision"
        finally:
            await db2.close()

    asyncio.run(_test())

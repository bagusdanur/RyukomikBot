"""Tests for Projects Tracker & RAW Comparison feature."""

import pytest
import asyncio
from dashboard.backend.routers.projects import (
    _generate_missing_chapters,
    _chapter_number,
    _format_chapter,
    list_projects,
    set_project_raw_source,
    ProjectSetRawRequest,
)
import database as db_module
import project_scout as scout_service
import pair_workflow as pair_service


def test_chapter_helpers():
    assert _chapter_number("Chapter 4") == 4.0
    assert _chapter_number("Ch. 5.5") == 5.5
    assert _chapter_number("271") == 271.0
    assert _chapter_number("None") is None

    assert _format_chapter(4.0) == "4"
    assert _format_chapter(5.5) == "5.5"
    assert _format_chapter(None) is None


def test_generate_missing_chapters():
    # Project at Ch 4, RAW at Ch 6 -> missing ["5", "6"]
    missing = _generate_missing_chapters(4.0, 6.0)
    assert missing == ["5", "6"]

    # Project at Ch 4, RAW at Ch 5 -> missing ["5"]
    missing = _generate_missing_chapters(4.0, 5.0)
    assert missing == ["5"]

    # Up to date: Project at Ch 6, RAW at Ch 6 -> []
    assert _generate_missing_chapters(6.0, 6.0) == []
    assert _generate_missing_chapters(7.0, 6.0) == []


def test_projects_list_and_raw_tracking(monkeypatch):
    async def _test():
        # Setup in-memory / local test database tables
        await db_module.setup_database()
        await scout_service.setup_scout_tables()
        await pair_service.setup_pair_tables()

        # Mock catalog fetch to return test projects
        sample_catalog = [
            {
                "title": "Get Out!",
                "slug": "get-out",
                "image": "https://storage.ryukomik.my.id/covers/get-out/cover.jpg",
                "status": "ongoing",
                "type_genre": "18+",
                "chapter_terbaru": "Chapter 4",
            },
            {
                "title": "Solo Leveling",
                "slug": "solo-leveling",
                "image": None,
                "status": "ongoing",
                "type_genre": "Manhwa",
                "chapter_terbaru": "Chapter 200",
            },
        ]

        import dashboard.backend.routers.projects as proj_router
        async def mock_fetch():
            return sample_catalog
        monkeypatch.setattr(proj_router, "_fetch_ryukomik_catalog", mock_fetch)

        # Insert a watch record: Get Out! on omega with RAW ch 6
        db = await db_module.get_db()
        try:
            await db.execute("DELETE FROM raw_chapter_watches WHERE manga_title='Get Out!'")
            await db.execute(
                """INSERT INTO raw_chapter_watches
                   (scout_title_id, source, source_id, manga_title, last_seen_chapter)
                   VALUES (0, 'omega', 'get-out', 'Get Out!', 6.0)"""
            )
            await db.commit()
        finally:
            await db.close()

        # Query projects list
        result = await list_projects(
            search="",
            status="all",
            source="all",
            page=1,
            page_size=20,
            _user={"id": "1", "role": "admin"},
        )

        assert result["total"] == 2
        get_out = next(item for item in result["items"] if item["title"] == "Get Out!")

        # Check comparison calculations
        assert get_out["project_chapter"] == 4.0
        assert get_out["raw_chapter"] == 6.0
        assert get_out["raw_source"] == "omega"
        assert get_out["chapter_gap"] == 2.0
        assert get_out["missing_chapters"] == ["5", "6"]
        assert get_out["next_task_chapter"] == "5"
        assert get_out["status"] == "raw_available"

        # Test filtering by status
        raw_avail_res = await list_projects(
            search="",
            status="raw_available",
            source="all",
            page=1,
            page_size=20,
            _user={"id": "1", "role": "admin"},
        )
        assert len(raw_avail_res["items"]) == 1
        assert raw_avail_res["items"][0]["title"] == "Get Out!"

        # Test filtering by source
        omega_res = await list_projects(
            search="",
            status="all",
            source="omega",
            page=1,
            page_size=20,
            _user={"id": "1", "role": "admin"},
        )
        assert len(omega_res["items"]) == 1
        assert omega_res["items"][0]["title"] == "Get Out!"

        # Test search query
        search_res = await list_projects(
            search="leveling",
            status="all",
            source="all",
            page=1,
            page_size=20,
            _user={"id": "1", "role": "admin"},
        )
        assert len(search_res["items"]) == 1
        assert search_res["items"][0]["title"] == "Solo Leveling"

    asyncio.run(_test())

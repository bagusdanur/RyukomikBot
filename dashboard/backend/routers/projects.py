"""Projects router — Ryukomik project catalog & RAW chapter tracking."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Literal, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import database as db_module
from config import PROJECT_PUBLIC_URL
from dashboard.backend.deps import admin_user, audit, current_user, dashboard_db
from dashboard.backend.helpers import enrich_staff
import project_scout as scout_service
from raw_downloader import get_downloader
from raw_downloader.resolver import normalize_title

router = APIRouter(prefix="/api/projects", tags=["projects"])

PROJECT_CATALOG_URL = os.getenv(
    "PROJECT_CATALOG_URL", "https://ryukomik.my.id/api/project/pustaka?limit=100"
)

RAW_DOWNLOADERS = scout_service.RAW_DOWNLOADERS


# ──────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────

class ProjectSetRawRequest(BaseModel):
    source: Literal[
        "asura", "omega", "doujiva", "evascan", "thunder", "vortex", "qimanga", "demon", "kagane", "mgeko"
    ]
    source_id: str = Field(min_length=1, max_length=150)


# ──────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────

def _chapter_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    matches = re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", "."))
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def _format_chapter(val: Optional[float]) -> Optional[str]:
    if val is None:
        return None
    return f"{val:g}"


def _generate_missing_chapters(project_ch: float, raw_ch: float) -> list[str]:
    """Generate chapter sequence from project_ch + 1 up to raw_ch."""
    if raw_ch <= project_ch:
        return []
    
    # If both are integers or round numbers
    if project_ch.is_integer() and raw_ch.is_integer():
        start = int(project_ch) + 1
        end = int(raw_ch)
        if start <= end:
            # If gap is huge (e.g. > 50), return next few and last
            if end - start > 20:
                return [str(start), str(start + 1), "...", str(end)]
            return [str(c) for c in range(start, end + 1)]
    
    # Otherwise return the next integer or raw chapter
    if project_ch + 1 <= raw_ch:
        return [f"{int(project_ch) + 1:g}", f"{raw_ch:g}"]
    return [f"{raw_ch:g}"]


async def _fetch_ryukomik_catalog() -> list[dict[str, Any]]:
    """Fetch all active projects from Ryukomik public catalog with fallback."""
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {"User-Agent": "RyukomikBot/1.0 (Staff Project Tracker)"}
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(PROJECT_CATALOG_URL, headers=headers) as response:
                if response.status == 200:
                    payload = await response.json(content_type=None)
                    rows = scout_service._catalog_rows(payload)
                    if rows:
                        return rows
    except Exception as err:
        print(f"[PROJECTS] Gagal mengambil katalog public: {err}", flush=True)

    # Fallback to local distinct manga titles from assignments
    connection = await dashboard_db()
    try:
        rows = await (await connection.execute(
            """SELECT manga AS title,
                      MAX(CAST(chapter AS REAL)) AS latest_ch,
                      MAX(assigned_at) AS last_activity
               FROM assignments
               GROUP BY manga
               ORDER BY last_activity DESC"""
        )).fetchall()
        return [
            {
                "title": row["title"],
                "slug": normalize_title(row["title"]),
                "chapter_terbaru": f"Chapter {_format_chapter(row['latest_ch']) or '1'}",
                "status": "ongoing",
                "image": None,
                "type_genre": "-",
            }
            for row in rows
        ]
    finally:
        await connection.close()


# ──────────────────────────────────────────────
# Router Endpoints
# ──────────────────────────────────────────────

@router.get("")
async def list_projects(
    search: str = Query(default="", max_length=100),
    status: str = Query(default="all"),
    source: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    _user=Depends(current_user),
):
    """List all Ryukomik projects with RAW chapter comparisons and active assignments."""
    search_q = str(search or "").strip() if isinstance(search, str) else ""
    status_filter = str(status or "all").strip() if isinstance(status, str) else "all"
    source_filter = str(source or "all").strip() if isinstance(source, str) else "all"
    page_val = int(page) if isinstance(page, (int, float)) else 1
    page_size_val = int(page_size) if isinstance(page_size, (int, float)) else 30

    catalog_items = await _fetch_ryukomik_catalog()
    
    connection = await dashboard_db()
    try:
        # Load all watches where scout_title_id = 0
        watch_rows = await (await connection.execute(
            "SELECT * FROM raw_chapter_watches WHERE scout_title_id=0"
        )).fetchall()
        
        # Load all assignments for quick mapping
        assignment_rows = await (await connection.execute(
            """SELECT id, manga, chapter, role, staff_id, status, deadline_at, assigned_at
               FROM assignments
               ORDER BY id DESC"""
        )).fetchall()
        enriched_assignments = await enrich_staff(assignment_rows)
    finally:
        await connection.close()

    # Index watches by normalized title and exact title
    watches_by_title: dict[str, dict[str, Any]] = {}
    for w in watch_rows:
        watches_by_title[str(w["manga_title"]).strip().casefold()] = dict(w)
        norm = normalize_title(str(w["manga_title"]))
        if norm:
            watches_by_title[norm] = dict(w)

    # Index assignments by manga title
    assignments_by_manga: dict[str, list[dict[str, Any]]] = {}
    for a in enriched_assignments:
        manga_key = str(a.get("manga") or "").strip().casefold()
        assignments_by_manga.setdefault(manga_key, []).append(a)
        norm_key = normalize_title(str(a.get("manga") or ""))
        if norm_key and norm_key != manga_key:
            assignments_by_manga.setdefault(norm_key, []).append(a)

    items: list[dict[str, Any]] = []
    
    # Process each catalog item
    seen_titles: set[str] = set()
    for cat in catalog_items:
        title = str(cat.get("title") or "").strip()
        if not title or title.casefold() in seen_titles:
            continue
        seen_titles.add(title.casefold())

        slug = str(cat.get("slug") or normalize_title(title)).strip("/")
        cover_url = cat.get("image") or cat.get("cover_url") or cat.get("cover")
        pub_status = str(cat.get("status") or "ongoing").casefold()
        type_genre = str(cat.get("type_genre") or cat.get("type") or "-")
        info = str(cat.get("info") or "")

        project_ch = _chapter_number(cat.get("chapter_terbaru") or cat.get("latest_chapter"))

        # Look up watch record
        watch = watches_by_title.get(title.casefold()) or watches_by_title.get(normalize_title(title))
        raw_source = str(watch["source"]) if watch and watch.get("source") else None
        raw_source_id = str(watch["source_id"]) if watch and watch.get("source_id") else None
        raw_ch = float(watch["last_seen_chapter"]) if watch and watch.get("last_seen_chapter") is not None else None
        last_checked_at = str(watch["updated_at"]) if watch and watch.get("updated_at") else None
        watch_id = int(watch["id"]) if watch and watch.get("id") else None

        # Look up assignments
        m_assignments = assignments_by_manga.get(title.casefold()) or assignments_by_manga.get(normalize_title(title)) or []
        
        assigned_chapter_numbers = [
            _chapter_number(a.get("chapter")) for a in m_assignments if _chapter_number(a.get("chapter")) is not None
        ]
        latest_assigned_ch = max(assigned_chapter_numbers, default=None)

        # Calculate effective project chapter (maximum of catalog and assigned)
        effective_proj_ch = project_ch or latest_assigned_ch or 1.0

        # Calculate chapter gap
        chapter_gap = None
        missing_chapters: list[str] = []
        if raw_ch is not None and effective_proj_ch is not None:
            gap = max(0.0, raw_ch - effective_proj_ch)
            chapter_gap = gap
            if gap > 0:
                missing_chapters = _generate_missing_chapters(effective_proj_ch, raw_ch)

        # Active tasks currently in progress
        active_tasks = [
            a for a in m_assignments if a.get("status") in {"open", "claimed", "submitted", "revision"}
        ]
        active_task_chapters = {str(a.get("chapter")) for a in active_tasks}

        # Determine item status
        if not raw_source or raw_ch is None:
            item_status = "unlinked"
        elif chapter_gap is not None and chapter_gap > 0:
            # If all missing chapters are currently covered by active tasks
            next_ch_str = missing_chapters[0] if missing_chapters else None
            if next_ch_str and next_ch_str in active_task_chapters:
                item_status = "in_progress"
            else:
                item_status = "raw_available"
        elif active_tasks:
            item_status = "in_progress"
        else:
            item_status = "up_to_date"

        # Next chapter suggestion for quick task button
        next_task_chapter = None
        if missing_chapters and missing_chapters[0] != "...":
            next_task_chapter = missing_chapters[0]
        elif raw_ch is not None and raw_ch > effective_proj_ch:
            next_task_chapter = _format_chapter(effective_proj_ch + 1)
        elif effective_proj_ch is not None:
            next_task_chapter = _format_chapter(effective_proj_ch + 1)
        else:
            next_task_chapter = "1"

        project_url = f"{PROJECT_PUBLIC_URL}/komik/project/{slug}" if slug else PROJECT_PUBLIC_URL

        items.append({
            "id": watch_id,
            "title": title,
            "slug": slug,
            "cover_url": cover_url,
            "publication_status": pub_status,
            "type_genre": type_genre,
            "info": info,
            "project_chapter": project_ch,
            "latest_assigned_chapter": latest_assigned_ch,
            "effective_chapter": effective_proj_ch,
            "raw_source": raw_source,
            "raw_source_id": raw_source_id,
            "raw_chapter": raw_ch,
            "chapter_gap": chapter_gap,
            "missing_chapters": missing_chapters,
            "next_task_chapter": next_task_chapter,
            "active_tasks_count": len(active_tasks),
            "active_tasks": [
                {
                    "id": a["id"],
                    "chapter": a["chapter"],
                    "role": a["role"],
                    "staff_name": a.get("staff_name") or "Belum di-claim",
                    "status": a["status"],
                }
                for a in active_tasks[:5]
            ],
            "status": item_status,
            "last_checked_at": last_checked_at,
            "project_url": project_url,
        })

    # Summary statistics before filters
    summary = {
        "total_projects": len(items),
        "raw_available_count": sum(1 for i in items if i["status"] == "raw_available"),
        "in_progress_count": sum(1 for i in items if i["status"] == "in_progress"),
        "up_to_date_count": sum(1 for i in items if i["status"] == "up_to_date"),
        "unlinked_count": sum(1 for i in items if i["status"] == "unlinked"),
    }

    # Apply Search Filter
    if search_q:
        q = search_q.casefold()
        items = [i for i in items if q in i["title"].casefold() or q in i["slug"].casefold()]

    # Apply Status Filter
    if status_filter and status_filter != "all":
        items = [i for i in items if i["status"] == status_filter]

    # Apply Source Filter
    if source_filter and source_filter != "all":
        items = [i for i in items if (i["raw_source"] or "").casefold() == source_filter.casefold()]

    # Sort items: raw_available first (by chapter_gap DESC), then in_progress, then up_to_date, then unlinked
    status_priority = {"raw_available": 0, "in_progress": 1, "up_to_date": 2, "unlinked": 3}
    items.sort(
        key=lambda i: (
            status_priority.get(i["status"], 4),
            -(i["chapter_gap"] or 0),
            i["title"].casefold(),
        )
    )

    # Pagination
    total = len(items)
    total_pages = max(1, (total + page_size_val - 1) // page_size_val)
    page_current = max(1, min(page_val, total_pages))
    start = (page_current - 1) * page_size_val
    paged_items = items[start : start + page_size_val]

    return {
        "items": paged_items,
        "summary": summary,
        "page": page_current,
        "page_size": page_size_val,
        "total": total,
        "total_pages": total_pages,
    }


@router.post("/sync")
async def sync_all_projects_raw(user=Depends(admin_user)):
    """Trigger background check for all Ryukomik active projects against RAW sources."""
    try:
        updates = await scout_service.poll_active_raw_updates()
        await audit(
            user["id"],
            "projects.sync_raw_all",
            "projects",
            0,
            after={"updates_count": len(updates), "updates": updates},
        )
        return {
            "ok": True,
            "updates_count": len(updates),
            "message": f"Sinkronisasi selesai. Ditemukan {len(updates)} pembaruan chapter RAW baru.",
            "updates": updates,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Gagal melakukan sinkronisasi RAW: {err}")


@router.post("/{project_slug}/sync")
async def sync_single_project_raw(project_slug: str, user=Depends(admin_user)):
    """Sync RAW status for a specific project by title or slug."""
    project_slug = project_slug.strip()
    catalog_items = await _fetch_ryukomik_catalog()
    matched = next(
        (
            item
            for item in catalog_items
            if str(item.get("slug") or "").strip("/").casefold() == project_slug.casefold()
            or normalize_title(str(item.get("title") or "")) == normalize_title(project_slug)
        ),
        None,
    )
    title = str(matched.get("title") if matched else project_slug).strip()
    project_ch = _chapter_number(matched.get("chapter_terbaru") if matched else None) or 1.0

    connection = await dashboard_db()
    try:
        watch = await (await connection.execute(
            "SELECT * FROM raw_chapter_watches WHERE scout_title_id=0 AND (manga_title=? OR manga_title=?) ORDER BY id DESC LIMIT 1",
            (title, project_slug),
        )).fetchone()
    finally:
        await connection.close()

    source: str
    source_id: str
    if watch:
        source, source_id = str(watch["source"]), str(watch["source_id"])
    else:
        discovered = await scout_service._discover_project_raw(title)
        if not discovered:
            raise HTTPException(
                status_code=404,
                detail=f"Tidak dapat menemukan sumber RAW otomatis untuk '{title}'. Silakan atur sumber RAW secara manual.",
            )
        source, source_id = discovered

    try:
        downloader = get_downloader(source)
        chapters = await downloader.get_chapter_list(source_id)
    except Exception as err:
        raise HTTPException(
            status_code=502,
            detail=f"Gagal mengambil daftar chapter dari {source.title()} ({source_id}): {err}",
        )

    latest = max((
        number
        for number in (_chapter_number(item.get("title") or item.get("id")) for item in chapters)
        if number is not None
    ), default=None)

    if latest is None:
        raise HTTPException(status_code=404, detail="Tidak ada chapter yang terbaca dari sumber RAW.")

    connection = await dashboard_db()
    try:
        if not watch:
            cursor = await connection.execute(
                """INSERT INTO raw_chapter_watches
                   (scout_title_id, source, source_id, manga_title, last_seen_chapter, last_notified_chapter)
                   VALUES (0, ?, ?, ?, ?, NULL)""",
                (source, source_id, title, latest),
            )
            watch_id = int(cursor.lastrowid)
        else:
            watch_id = int(watch["id"])
            await connection.execute(
                """UPDATE raw_chapter_watches
                   SET source=?, source_id=?, last_seen_chapter=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (source, source_id, latest, watch_id),
            )
        await connection.commit()
    finally:
        await connection.close()

    gap = max(0.0, latest - project_ch)
    await audit(
        user["id"],
        "projects.sync_single",
        "project",
        watch_id,
        after={"title": title, "source": source, "source_id": source_id, "latest_raw": latest, "gap": gap},
    )

    return {
        "ok": True,
        "title": title,
        "source": source,
        "source_id": source_id,
        "project_chapter": project_ch,
        "raw_chapter": latest,
        "chapter_gap": gap,
        "total_raw_chapters": len(chapters),
        "message": f"RAW diperbarui: {source.title()} Ch. {latest:g} (Ryukomik Ch. {project_ch:g})",
    }


@router.post("/{project_slug}/set-raw")
async def set_project_raw_source(
    project_slug: str, payload: ProjectSetRawRequest, user=Depends(admin_user)
):
    """Manually link or override the RAW source and slug for a Ryukomik project."""
    project_slug = project_slug.strip()
    catalog_items = await _fetch_ryukomik_catalog()
    matched = next(
        (
            item
            for item in catalog_items
            if str(item.get("slug") or "").strip("/").casefold() == project_slug.casefold()
            or normalize_title(str(item.get("title") or "")) == normalize_title(project_slug)
        ),
        None,
    )
    title = str(matched.get("title") if matched else project_slug).strip()

    # Validate that source_id exists on the given downloader
    try:
        downloader = get_downloader(payload.source)
        chapters = await downloader.get_chapter_list(payload.source_id.strip())
    except Exception as err:
        raise HTTPException(
            status_code=400,
            detail=f"Slug '{payload.source_id}' tidak valid atau tidak dapat diakses di {payload.source.title()}: {err}",
        )

    latest = max((
        number
        for number in (_chapter_number(item.get("title") or item.get("id")) for item in chapters)
        if number is not None
    ), default=None)

    connection = await dashboard_db()
    try:
        watch = await (await connection.execute(
            "SELECT id FROM raw_chapter_watches WHERE scout_title_id=0 AND (manga_title=? OR manga_title=?)",
            (title, project_slug),
        )).fetchone()

        if watch:
            watch_id = int(watch["id"])
            await connection.execute(
                """UPDATE raw_chapter_watches
                   SET source=?, source_id=?, last_seen_chapter=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (payload.source, payload.source_id.strip(), latest, watch_id),
            )
        else:
            cursor = await connection.execute(
                """INSERT INTO raw_chapter_watches
                   (scout_title_id, source, source_id, manga_title, last_seen_chapter, last_notified_chapter)
                   VALUES (0, ?, ?, ?, ?, NULL)""",
                (payload.source, payload.source_id.strip(), title, latest),
            )
            watch_id = int(cursor.lastrowid)
        await connection.commit()
    finally:
        await connection.close()

    await audit(
        user["id"],
        "projects.set_raw_source",
        "project",
        watch_id,
        after={"title": title, "source": payload.source, "source_id": payload.source_id, "latest_raw": latest},
    )

    return {
        "ok": True,
        "title": title,
        "source": payload.source,
        "source_id": payload.source_id,
        "raw_chapter": latest,
        "total_chapters": len(chapters),
        "message": f"Sumber RAW untuk '{title}' berhasil dihubungkan ke {payload.source.title()} ({payload.source_id}).",
    }


@router.get("/{project_slug}/raw-chapters")
async def get_project_raw_chapters(project_slug: str, _user=Depends(current_user)):
    """Fetch live list of available chapters on the linked RAW downloader."""
    project_slug = project_slug.strip()
    catalog_items = await _fetch_ryukomik_catalog()
    matched = next(
        (
            item
            for item in catalog_items
            if str(item.get("slug") or "").strip("/").casefold() == project_slug.casefold()
            or normalize_title(str(item.get("title") or "")) == normalize_title(project_slug)
        ),
        None,
    )
    title = str(matched.get("title") if matched else project_slug).strip()

    connection = await dashboard_db()
    try:
        watch = await (await connection.execute(
            "SELECT * FROM raw_chapter_watches WHERE scout_title_id=0 AND (manga_title=? OR manga_title=?) ORDER BY id DESC LIMIT 1",
            (title, project_slug),
        )).fetchone()
    finally:
        await connection.close()

    if not watch or not watch.get("source") or not watch.get("source_id"):
        raise HTTPException(
            status_code=404,
            detail=f"Project '{title}' belum memiliki sumber RAW yang terhubung.",
        )

    source, source_id = str(watch["source"]), str(watch["source_id"])
    try:
        downloader = get_downloader(source)
        chapters = await downloader.get_chapter_list(source_id)
        return {
            "title": title,
            "source": source,
            "source_id": source_id,
            "chapters": chapters,
        }
    except Exception as err:
        raise HTTPException(
            status_code=502,
            detail=f"Gagal mengambil chapter dari {source.title()} ({source_id}): {err}",
        )

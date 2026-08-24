"""QC Router — Side-by-Side Quality Control & Image Inspection Studio."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import database as db_module
from dashboard.backend.deps import admin_user, current_user, dashboard_db
from dashboard.backend.helpers import enrich_staff
from dashboard.backend.routers.assignments import (
    RevisionRequest,
    dashboard_approve_assignment,
    dashboard_revision_assignment,
)
from raw_downloader import (
    asura_downloader,
    demon_downloader,
    doujiva_downloader,
    diva_downloader,
    evascan_downloader,
    get_downloader,
    omega_downloader,
    qimanga_downloader,
    thunder_downloader,
    vortex_downloader,
    kagane_downloader,
    mgeko_downloader,
)
from raw_downloader.resolver import normalize_title, resolve_assignment_raw

router = APIRouter(prefix="/api/qc", tags=["qc"])


class PageAnnotation(BaseModel):
    page: int = Field(ge=1)
    comment: str = Field(min_length=1, max_length=500)


class QcReviseRequest(BaseModel):
    notes: str = Field(default="", max_length=1500)
    page_notes: List[PageAnnotation] = Field(default_factory=list)


def _clean_chapter(chapter_str: str) -> str:
    """Normalize chapter string for downloader endpoints (e.g. 'Chapter 4' -> '4')."""
    raw = str(chapter_str or "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)", raw)
    return match.group(1) if match else raw


async def _resolve_raw_images(manga_title: str, chapter: str) -> tuple[List[str], Optional[str]]:
    """Find RAW downloader & fetch ordered chapter images."""
    clean_chap = _clean_chapter(chapter)
    connection = await dashboard_db()
    watch_row = None
    try:
        # Check if there's an existing watch binding
        watch_row = await (
            await connection.execute(
                """SELECT source, source_id FROM raw_chapter_watches
                   WHERE manga_title = ? OR manga_title LIKE ?
                   ORDER BY id DESC LIMIT 1""",
                (manga_title, f"%{manga_title}%"),
            )
        ).fetchone()
    finally:
        await connection.close()

    source = None
    source_id = None
    if watch_row:
        source = watch_row["source"]
        source_id = watch_row["source_id"]

    # Fallback to dynamic resolver if not found in watches
    if not source or not source_id:
        try:
            resolved = await resolve_assignment_raw(
                manga_title,
                [clean_chap],
                {
                    "omega": omega_downloader,
                    "asura": asura_downloader,
                    "doujiva": doujiva_downloader,
                    "diva": diva_downloader,
                    "evascan": evascan_downloader,
                    "thunder": thunder_downloader,
                    "vortex": vortex_downloader,
                    "qimanga": qimanga_downloader,
                    "demon": demon_downloader,
                    "kagane": kagane_downloader,
                    "mgeko": mgeko_downloader,
                },
                timeout=8,
            )
            if resolved and resolved.get("best"):
                best = resolved["best"]
                source = best.get("_source") or best.get("source")
                source_id = best.get("id") or best.get("manga_id") or best.get("slug")
        except Exception as err:
            print(f"[QC] Auto resolve error: {err}", flush=True)

    if not source or not source_id:
        return [], None

    downloader = get_downloader(source)
    if not downloader:
        return [], source

    try:
        # Fetch chapter images from scraper
        images = await asyncio.wait_for(
            downloader.get_chapter_images(source_id, clean_chap),
            timeout=15,
        )
        return images or [], source
    except Exception as error:
        print(f"[QC] Failed to fetch RAW images for {manga_title} Ch. {clean_chap} from {source}: {error}", flush=True)
        return [], source


def _parse_gdrive_folder_id(link: str) -> Optional[str]:
    """Extract folder ID from Google Drive URLs."""
    if not link:
        return None
    match = re.search(r"folders/([a-zA-Z0-9_-]+)", link)
    if match:
        return match.group(1)
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", link)
    if match:
        return match.group(1)
    return None


def _natural_sort_key(s: str) -> list:
    """Helper for natural alphanumeric sorting (e.g. '01.png', '2.png', '10.png')."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


async def _extract_gdrive_folder_images(folder_id: str) -> List[Dict[str, str]]:
    """Extract image file list and direct view URLs from a public Google Drive folder."""
    if not folder_id:
        return []
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()

                ivd_match = re.search(r"window\['_DRIVE_ivd'\]\s*=\s*'([^']*)'", html)
                if not ivd_match:
                    return []

                raw = ivd_match.group(1)
                decoded_json_str = bytes(raw, "utf-8").decode("unicode_escape")
                data = json.loads(decoded_json_str)

                files = []

                def walk(obj):
                    if isinstance(obj, list):
                        if (
                            len(obj) >= 4
                            and isinstance(obj[0], str)
                            and len(obj[0]) in range(25, 45)
                            and isinstance(obj[2], str)
                        ):
                            name = obj[2]
                            mime = obj[3] if len(obj) > 3 else ""
                            if (
                                any(name.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"))
                                or "image" in str(mime).lower()
                            ):
                                file_id = obj[0]
                                files.append({
                                    "id": file_id,
                                    "name": name,
                                    "url": f"https://lh3.googleusercontent.com/d/{file_id}",
                                })
                        for child in obj:
                            walk(child)

                walk(data)
                return sorted(files, key=lambda x: _natural_sort_key(x["name"]))
        except Exception as error:
            print(f"[QC] Failed to extract Google Drive images from folder {folder_id}: {error}", flush=True)
            return []


async def _extract_filebin_images(bin_id: str) -> List[Dict[str, str]]:
    """Extract image file list from Filebin URL."""
    if not bin_id:
        return []
    url = f"https://filebin.net/api/bins/{bin_id}"
    headers = {"Accept": "application/json"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                files = []
                for item in data.get("files", []):
                    fname = item.get("filename", "")
                    if any(fname.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
                        files.append({
                            "id": fname,
                            "name": fname,
                            "url": f"https://filebin.net/{bin_id}/{fname}",
                        })
                return sorted(files, key=lambda x: _natural_sort_key(x["name"]))
        except Exception as error:
            print(f"[QC] Failed to extract Filebin images from {bin_id}: {error}", flush=True)
            return []


async def _extract_submission_images(link: str) -> List[Dict[str, str]]:
    """Extract ordered image list from Google Drive or Filebin submission links."""
    if not link:
        return []
    link = link.strip()

    # 1. Google Drive Folder
    folder_id = _parse_gdrive_folder_id(link)
    if folder_id:
        return await _extract_gdrive_folder_images(folder_id)

    # 2. Google Drive Single File
    single_file_match = re.search(r"file/d/([a-zA-Z0-9_-]+)", link) or re.search(r"[?&]id=([a-zA-Z0-9_-]+)", link)
    if single_file_match and "folders" not in link:
        file_id = single_file_match.group(1)
        return [{
            "id": file_id,
            "name": "Hasil Staff",
            "url": f"https://lh3.googleusercontent.com/d/{file_id}",
        }]

    # 3. Filebin Link
    filebin_match = re.search(r"filebin\.net/([a-zA-Z0-9_-]+)", link)
    if filebin_match:
        return await _extract_filebin_images(filebin_match.group(1))

    return []


@router.get("/{assignment_id}")
async def get_qc_details(assignment_id: int, user=Depends(current_user)):
    """Fetch assignment data, RAW images, and submission details for QC inspection."""
    connection = await dashboard_db()
    try:
        row = await (
            await connection.execute(
                "SELECT * FROM assignments WHERE id = ?", (assignment_id,)
            )
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tugas tidak ditemukan.")

        assignment_dict = dict(row)
        enriched = await enrich_staff([assignment_dict])
        assignment = enriched[0] if enriched else assignment_dict
    finally:
        await connection.close()

    # Permission check: Admin or the assigned staff
    if user.get("role") != "admin" and str(assignment.get("staff_id")) != str(user.get("id")):
        raise HTTPException(status_code=403, detail="Anda tidak memiliki akses ke tugas ini.")

    manga_title = assignment.get("manga", "")
    chapter = assignment.get("chapter", "")
    gdrive_link = assignment.get("gdrive_link") or ""

    # Fetch RAW images and Staff Submission images concurrently
    (raw_images, raw_source), submission_files = await asyncio.gather(
        _resolve_raw_images(manga_title, chapter),
        _extract_submission_images(gdrive_link),
    )

    gdrive_folder_id = _parse_gdrive_folder_id(gdrive_link)
    gdrive_embed_url = (
        f"https://drive.google.com/embeddedfolderview?id={gdrive_folder_id}#grid"
        if gdrive_folder_id
        else None
    )

    submission_pages = [item["url"] for item in submission_files] if submission_files else []

    return {
        "assignment": assignment,
        "raw_pages": raw_images,
        "raw_source": raw_source,
        "raw_page_count": len(raw_images),
        "gdrive_link": gdrive_link,
        "gdrive_folder_id": gdrive_folder_id,
        "gdrive_embed_url": gdrive_embed_url,
        "submission_pages": submission_pages,
        "submission_files": submission_files,
        "submission_count": len(submission_pages),
    }


@router.post("/{assignment_id}/approve")
async def qc_approve(assignment_id: int, user=Depends(admin_user)):
    """Approve assignment directly from QC viewer."""
    return await dashboard_approve_assignment(assignment_id, user=user)


@router.post("/{assignment_id}/revise")
async def qc_revise(
    assignment_id: int, payload: QcReviseRequest, user=Depends(admin_user)
):
    """Request revision from QC viewer with formatted page notes."""
    notes_parts = []
    if payload.notes.strip():
        notes_parts.append(payload.notes.strip())

    if payload.page_notes:
        notes_parts.append("\n📋 **Catatan Per Halaman:**")
        for item in sorted(payload.page_notes, key=lambda x: x.page):
            notes_parts.append(f"• **Hal. {item.page}**: {item.comment.strip()}")

    full_notes = "\n".join(notes_parts).strip()
    if not full_notes:
        raise HTTPException(
            status_code=422, detail="Berikan catatan revisi untuk staff."
        )

    revision_payload = RevisionRequest(notes=full_notes[:1500])
    return await dashboard_revision_assignment(
        assignment_id, revision_payload, user=user
    )


@router.get("/proxy-image")
async def proxy_qc_image(url: str, user=Depends(current_user)):
    """Proxy RAW image if direct hotlink is blocked by origin CDN referer protection."""
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid URL protocol.")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    raise HTTPException(
                        status_code=resp.status,
                        detail="Gagal mengambil gambar dari sumber.",
                    )
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                content = await resp.read()
                return Response(
                    content=content,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                    },
                )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Proxy error: {e}")

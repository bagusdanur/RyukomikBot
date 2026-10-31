"""RAW downloader API untuk dipakai dari server lain (API key, bukan cookie).

Alur singkat:
    POST /api/v1/raw/fetch   {"title": "...", "chapter": "1", "source": "mangadex"}
    GET  /api/v1/raw/status/{token}
    GET  /api/v1/raw/download/{token}?mode=joined

Untuk pemakaian satu langkah (tanpa polling):
    GET  /api/v1/raw/get?title=...&chapter=1&mode=joined
Endpoint ini menunggu sampai paket siap lalu mengirim ZIP-nya.

Autentikasi: header `X-API-Key: <RAW_API_KEY>` (atau `Authorization: Bearer ...`).
"""
from __future__ import annotations

import asyncio
import difflib
import os
import re
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from raw_downloader import get_downloader
from dashboard.backend import raw_exports

router = APIRouter(prefix="/api/v1/raw", tags=["raw-api"])

OWNER = "raw-api"
SOURCES = ["mangadex", "asura", "thunder", "evascan", "mist", "lua", "vortex", "qimanga", "demon", "kagane", "mgread"]
DEFAULT_SOURCE = os.getenv("RAW_API_DEFAULT_SOURCE", "mangadex")
LANG_ORDER = ["en", "id", "es-la", "es", "pt-br", "fr", "ru", "ar"]


def require_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    expected = os.getenv("RAW_API_KEY", "").strip()
    if not expected:
        raise HTTPException(503, "RAW_API_KEY belum diset di server.")
    given = (x_api_key or "").strip()
    if not given and authorization and authorization.lower().startswith("bearer "):
        given = authorization[7:].strip()
    if not given or not secrets.compare_digest(given, expected):
        raise HTTPException(401, "API key salah.")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).casefold()).strip()


def _chapter_number(title: str) -> float | None:
    match = re.search(r"chapter\s*([0-9]+(?:\.[0-9]+)?)", str(title), re.I)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _chapter_lang(title: str) -> str:
    match = re.search(r"\[([a-zA-Z-]+)\]\s*$", str(title))
    return match.group(1).lower() if match else ""


def _pick_manga(rows: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    if not rows:
        return None
    wanted = _norm(title)
    scored = sorted(
        rows,
        key=lambda row: difflib.SequenceMatcher(None, wanted, _norm(row.get("title", ""))).ratio(),
        reverse=True,
    )
    best = scored[0]
    score = difflib.SequenceMatcher(None, wanted, _norm(best.get("title", ""))).ratio()
    return best if score >= 0.55 else None


def _pick_chapter(rows: list[dict[str, Any]], chapter: str | None) -> dict[str, Any] | None:
    if not rows:
        return None
    if not chapter:
        return rows[0]
    try:
        wanted = float(str(chapter).strip())
    except ValueError:
        wanted = None
    candidates = []
    for row in rows:
        number = _chapter_number(row.get("title", ""))
        if wanted is not None and number is not None and abs(number - wanted) < 1e-6:
            candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda row: LANG_ORDER.index(_chapter_lang(row.get("title", "")))
                    if _chapter_lang(row.get("title", "")) in LANG_ORDER else len(LANG_ORDER))
    return candidates[0]


async def _resolve(source: str | None, title: str | None, manga_id: str | None,
                   chapter: str | None) -> tuple[str, str, str, str]:
    """Kembalikan (source, manga_id, chapter_id, label_chapter)."""
    tried: list[str] = []
    order = [source] if source else ([DEFAULT_SOURCE] + [s for s in SOURCES if s != DEFAULT_SOURCE])
    for candidate in order:
        if not candidate:
            continue
        try:
            downloader = get_downloader(candidate)
        except ValueError:
            continue
        tried.append(candidate)
        mid = manga_id
        if not mid:
            if not title:
                raise HTTPException(400, "Isi `title` atau `manga_id`.")
            try:
                rows = await asyncio.wait_for(downloader.search_manga(title), timeout=40)
            except Exception:  # noqa: BLE001 - source berikutnya
                continue
            match = _pick_manga(rows or [], title)
            if not match:
                continue
            mid = str(match.get("id") or "")
        if not mid:
            continue
        try:
            chapters = await asyncio.wait_for(downloader.get_chapter_list(mid), timeout=60)
        except Exception:  # noqa: BLE001
            continue
        picked = _pick_chapter(chapters or [], chapter)
        if picked:
            return candidate, mid, str(picked.get("id") or ""), str(picked.get("title") or "")
    raise HTTPException(404, f"Judul/chapter tidak ditemukan. Source dicoba: {', '.join(tried) or '-'}.")


@router.get("/sources", dependencies=[Depends(require_key)])
async def raw_sources() -> dict[str, Any]:
    return {"sources": SOURCES, "default": DEFAULT_SOURCE}


@router.get("/search", dependencies=[Depends(require_key)])
async def raw_search(q: str = Query(min_length=2), source: str | None = None) -> dict[str, Any]:
    order = [source] if source else SOURCES
    results: list[dict[str, Any]] = []
    for candidate in order:
        try:
            downloader = get_downloader(candidate)
        except ValueError:
            continue
        try:
            rows = await asyncio.wait_for(downloader.search_manga(q), timeout=30)
        except Exception:  # noqa: BLE001
            continue
        for row in rows or []:
            results.append({"source": candidate, "id": str(row.get("id") or ""), "title": row.get("title") or ""})
        if results and not source:
            break
    return {"query": q, "results": results[:30]}


@router.get("/chapters", dependencies=[Depends(require_key)])
async def raw_chapters(source: str, manga_id: str) -> dict[str, Any]:
    try:
        downloader = get_downloader(source)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    chapters = await asyncio.wait_for(downloader.get_chapter_list(manga_id), timeout=60)
    return {"source": source, "manga_id": manga_id, "count": len(chapters or []), "chapters": chapters[:400]}


@router.post("/fetch", dependencies=[Depends(require_key)])
async def raw_fetch(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    manga_id = str(payload.get("manga_id") or "").strip()
    chapter = str(payload.get("chapter") or "").strip() or None
    source = str(payload.get("source") or "").strip().lower() or None
    mode = str(payload.get("mode") or "original").strip().lower()
    if mode not in {"original", "joined"}:
        raise HTTPException(400, "mode harus `original` atau `joined`.")
    resolved_source, resolved_manga, chapter_id, label = await _resolve(source, title, manga_id, chapter)
    downloader = get_downloader(resolved_source)
    state = raw_exports.start(
        {"source": resolved_source, "manga_id": resolved_manga, "chapter_id": chapter_id, "mode": mode},
        OWNER, downloader,
    )
    token = state["token"]
    return {
        "token": token,
        "state": state["state"],
        "source": resolved_source,
        "manga_id": resolved_manga,
        "chapter_id": chapter_id,
        "chapter": label,
        "status_url": f"/api/v1/raw/status/{token}",
        "mode": mode,
        "download_url": f"/api/v1/raw/download/{token}?mode={mode}",
    }


@router.get("/status/{token}", dependencies=[Depends(require_key)])
async def raw_status(token: str) -> dict[str, Any]:
    _, state = raw_exports.read_state(token, OWNER)
    public = raw_exports.public_state(state)
    public["download"] = {mode: f"/api/v1/raw/download/{token}?mode={mode}"
                          for mode in ("original", "joined") if mode in state}
    return public


@router.get("/download/{token}", dependencies=[Depends(require_key)])
async def raw_download(token: str, mode: str = "joined") -> FileResponse:
    path, state = raw_exports.download_path(token, OWNER, mode)
    return FileResponse(path, filename=raw_exports.filename(state, mode), media_type="application/zip")


@router.get("/get", dependencies=[Depends(require_key)])
async def raw_get(
    title: str | None = None,
    manga_id: str | None = None,
    chapter: str | None = None,
    source: str | None = None,
    mode: str = "original",
    wait_seconds: int = Query(default=600, ge=30, le=1800),
) -> FileResponse:
    """Satu langkah: cari judul → siapkan → kirim ZIP."""
    if not title and not manga_id:
        raise HTTPException(400, "Isi `title` atau `manga_id`.")
    resolved = await _resolve(source, title, manga_id, chapter)
    downloader = get_downloader(resolved[0])
    state = raw_exports.start({"source": resolved[0], "manga_id": resolved[1],
                               "chapter_id": resolved[2], "mode": mode}, OWNER, downloader)
    token = state["token"]
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        await asyncio.sleep(3)
        _, current = raw_exports.read_state(token, OWNER)
        if current["state"] == "READY":
            if mode not in current:
                mode = "original"
            path, state = raw_exports.download_path(token, OWNER, mode)
            return FileResponse(path, filename=raw_exports.filename(state, mode), media_type="application/zip")
        if current["state"] == "FAILED":
            raise HTTPException(502, current.get("error") or "Penyiapan RAW gagal.")
    raise HTTPException(504, "RAW belum siap dalam batas waktu. Pakai /fetch lalu /status untuk polling.")

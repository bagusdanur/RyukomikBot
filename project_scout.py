"""Project Scout: compare RAW titles with Indonesian catalogues safely."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Optional
from urllib.parse import quote, urlparse

import aiohttp

import database as db_module
from raw_downloader import get_downloader
from raw_downloader import (
    asura_downloader,
    doujiva_downloader,
    evascan_downloader,
    omega_downloader,
    qimanga_downloader,
    demon_downloader,
    thunder_downloader,
)
from raw_downloader.resolver import normalize_title


API_BASE = os.getenv("SCOUT_API_BASE", "https://api.ryukomik.web.id").rstrip("/")
PROJECT_CATALOG_URL = os.getenv(
    "PROJECT_CATALOG_URL", "https://ryukomik.my.id/api/project/pustaka?limit=100"
)
INDONESIAN_SOURCES = ("komiku", "kiryuu", "ikiru", "sekte", "doujindesu", "komikid")
RAW_DOWNLOADERS = {
    "asura": asura_downloader,
    "omega": omega_downloader,
    "doujiva": doujiva_downloader,
    "evascan": evascan_downloader,
    "thunder": thunder_downloader,
    "qimanga": qimanga_downloader,
    "demon": demon_downloader,
}
CACHE_HOURS = max(1, int(os.getenv("SCOUT_CACHE_HOURS", "24")))
MAX_CONCURRENCY = max(1, min(10, int(os.getenv("SCOUT_MAX_CONCURRENCY", "5"))))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: Optional[str], fallback: Any) -> Any:
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def _slug(item: dict[str, Any]) -> str:
    if item.get("slug"):
        return str(item["slug"]).strip("/")
    link = str(item.get("detail_link") or item.get("url") or item.get("id") or "")
    parts = [part for part in urlparse(link).path.split("/") if part]
    return parts[-1] if parts else link.strip("/").split("/")[-1]


def _aliases(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("alternative_titles", "alternative_title", "alternatif", "other_titles", "aliases"):
        raw = item.get(key)
        if isinstance(raw, list):
            values.extend(str(entry).strip() for entry in raw if str(entry).strip())
        elif raw:
            values.extend(part.strip() for part in re.split(r"[,|;/]", str(raw)) if part.strip())
    return list(dict.fromkeys(values))


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


def _chapter_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("chapters", "chapter_list", "chapterList"):
            if isinstance(payload.get(key), list):
                return [entry for entry in payload[key] if isinstance(entry, dict)]
        for key in ("data", "result", "manga"):
            found = _chapter_list(payload.get(key))
            if found:
                return found
    return []


def _catalog_rows(payload: Any) -> list[dict[str, Any]]:
    """Extract catalogue rows from the slightly different /pustaka schemas."""
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "items", "manga"):
        value = payload.get(key)
        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, dict)]
        if isinstance(value, dict):
            rows = _catalog_rows(value)
            if rows:
                return rows
    return []


def _latest_chapter(item: dict[str, Any], detail: Optional[dict[str, Any]] = None) -> Optional[float]:
    chapters = _chapter_list(detail or {})
    numbers = [
        number for number in (
            _chapter_number(entry.get("chapter") or entry.get("title") or entry.get("id"))
            for entry in chapters
        ) if number is not None
    ]
    if numbers:
        return max(numbers)
    for source in (detail or {}, item):
        for key in ("latest_chapter", "chapter_terbaru", "update", "chapter", "latest"):
            number = _chapter_number(source.get(key))
            if number is not None:
                return number
    return None


def _title_score(query: str, title: str, aliases: Optional[list[str]] = None) -> int:
    left = normalize_title(query)
    candidates = [normalize_title(title), *(normalize_title(alias) for alias in aliases or [])]
    candidates = [candidate for candidate in candidates if candidate]
    if not left or not candidates:
        return 0
    scores = []
    for candidate in candidates:
        if left == candidate:
            scores.append(100)
            continue
        ratio = SequenceMatcher(None, left, candidate).ratio()
        left_words, candidate_words = set(left.split()), set(candidate.split())
        overlap = len(left_words & candidate_words) / max(1, len(left_words | candidate_words))
        scores.append(round(max(ratio, overlap) * 100))
    return max(scores)


def _normalise_entry(source: str, group: str, item: dict[str, Any], detail: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    detail_data = detail.get("data") if isinstance(detail, dict) and isinstance(detail.get("data"), dict) else detail or {}
    title = str(item.get("title") or detail_data.get("title") or "").strip()
    if source == "komiku" and title.casefold().startswith("komik "):
        title = title[6:].strip()
    genres = detail_data.get("genres") or item.get("genres") or []
    if isinstance(genres, str):
        genres = [part.strip() for part in genres.split(",") if part.strip()]
    return {
        "source": source,
        "source_group": group,
        "source_id": str(item.get("id") or _slug(item)),
        "slug": _slug(item),
        "title": title,
        "normalized_title": normalize_title(title),
        "alternative_titles": _aliases({**item, **detail_data}),
        "cover_url": detail_data.get("thumbnail") or detail_data.get("image") or item.get("image") or item.get("cover"),
        "synopsis": detail_data.get("synopsis") or detail_data.get("description") or item.get("synopsis") or item.get("description") or "",
        "genres": genres if isinstance(genres, list) else [],
        "content_type": detail_data.get("type") or detail_data.get("type_genre") or item.get("type") or item.get("type_genre"),
        "publication_status": detail_data.get("status") or item.get("status"),
        "latest_chapter": _latest_chapter(item, detail),
        "chapter_count": len(_chapter_list(detail or {})) or item.get("chapter_count"),
        "detail_url": item.get("detail_link") or item.get("url"),
    }


async def _request_json(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    for attempt, delay in enumerate((0, 0.5, 1.0), start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with session.get(url) as response:
                if response.status == 404:
                    return {}
                if response.status == 429 or response.status >= 500:
                    if attempt < 3:
                        continue
                    return {}
                if response.status >= 400:
                    return {}
                payload = await response.json(content_type=None)
                return payload if isinstance(payload, dict) else {}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            if attempt == 3:
                return {}
    return {}


async def _search_indonesian(query: str) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def search(source: str) -> list[dict[str, Any]]:
            # /pustaka is the canonical Indonesian catalogue.  Only fetch its
            # first (freshest) page here; some catalogues have hundreds of pages.
            async with semaphore:
                payload = await _request_json(session, f"{API_BASE}/{source}/pustaka?page=1")
            rows = _catalog_rows(payload)
            ranked = sorted(
                (( _title_score(query, str(row.get("title") or ""), _aliases(row)), row) for row in rows if isinstance(row, dict)),
                key=lambda pair: pair[0], reverse=True,
            )

            # A direct lookup prevents older catalogue entries from being
            # missed without downloading every /pustaka page on every scan.
            if not ranked or ranked[0][0] < 90:
                async with semaphore:
                    lookup = await _request_json(
                        session, f"{API_BASE}/{source}/search?q={quote(query, safe='')}"
                    )
                lookup_rows = _catalog_rows(lookup)
                combined = {
                    str(row.get("id") or _slug(row) or row.get("title")): row
                    for row in (*rows, *lookup_rows)
                    if isinstance(row, dict)
                }
                ranked = sorted(
                    ((_title_score(query, str(row.get("title") or ""), _aliases(row)), row)
                     for row in combined.values()),
                    key=lambda pair: pair[0], reverse=True,
                )
            output = []
            for score, item in ranked[:3]:
                detail = {}
                slug = _slug(item)
                if score >= 55 and slug:
                    async with semaphore:
                        detail = await _request_json(session, f"{API_BASE}/{source}/detail/{quote(slug, safe='')}")
                entry = _normalise_entry(source, "indonesia", item, detail)
                entry["match_score"] = _title_score(query, entry["title"], entry["alternative_titles"])
                output.append(entry)
            return output

        results = await asyncio.gather(*(search(source) for source in INDONESIAN_SOURCES))
    return [entry for group in results for entry in group]


async def _search_raw(query: str, selected_source: str) -> list[dict[str, Any]]:
    sources = list(RAW_DOWNLOADERS) if selected_source == "all" else [selected_source]
    if any(source not in RAW_DOWNLOADERS for source in sources):
        raise ValueError("Sumber RAW tidak dikenal.")

    async def search(source: str) -> list[dict[str, Any]]:
        try:
            rows = await RAW_DOWNLOADERS[source].search_manga(query)
        except Exception:
            return []
        ranked = sorted(
            ((_title_score(query, str(row.get("title") or "")), row) for row in rows if isinstance(row, dict)),
            key=lambda pair: pair[0], reverse=True,
        )
        output = []
        for score, item in ranked[:2]:
            entry = _normalise_entry(source, "raw", item)
            entry["match_score"] = score
            if score >= 70 and item.get("id"):
                try:
                    chapters = await RAW_DOWNLOADERS[source].get_chapter_list(str(item["id"]))
                    numbers = [
                        number for number in (
                            _chapter_number(row.get("title") or row.get("id")) for row in chapters
                        ) if number is not None
                    ]
                    entry["latest_chapter"] = max(numbers) if numbers else entry["latest_chapter"]
                    entry["chapter_count"] = len(chapters)
                except Exception:
                    pass
            output.append(entry)
        return output

    results = await asyncio.gather(*(search(source) for source in sources))
    return [entry for group in results for entry in group]


async def _local_projects(query: str) -> list[dict[str, Any]]:
    db = await db_module.get_db()
    try:
        rows = await (await db.execute(
            "SELECT manga,MAX(CAST(chapter AS REAL)) latest_chapter FROM assignments GROUP BY manga"
        )).fetchall()
    finally:
        await db.close()
    entries = []
    for row in rows:
        score = _title_score(query, row["manga"])
        if score >= 55:
            entries.append({
                "source": "ryukomik", "source_group": "internal",
                "source_id": normalize_title(row["manga"]), "slug": normalize_title(row["manga"]).replace(" ", "-"),
                "title": row["manga"], "normalized_title": normalize_title(row["manga"]),
                "alternative_titles": [], "cover_url": None, "synopsis": "", "genres": [],
                "content_type": None, "publication_status": "Project Ryukomik",
                "latest_chapter": row["latest_chapter"], "chapter_count": None,
                "detail_url": None, "match_score": score,
            })
    return entries


def _classify(raw_entries: list[dict[str, Any]], comparison_entries: list[dict[str, Any]]) -> dict[str, Any]:
    primary = max(raw_entries, key=lambda item: (item.get("match_score", 0), item.get("latest_chapter") or 0))
    query = primary["title"]
    matches = []
    for entry in comparison_entries:
        score = _title_score(query, entry["title"], entry.get("alternative_titles"))
        matches.append({**entry, "match_score": score})
    matches.sort(key=lambda item: item["match_score"], reverse=True)
    best = matches[0] if matches else None
    confidence = int(best["match_score"]) if best else 0
    raw_latest = max((entry.get("latest_chapter") or 0 for entry in raw_entries), default=0) or None
    indo_latest = max((entry.get("latest_chapter") or 0 for entry in matches if entry["match_score"] >= 90), default=0) or None
    internal = next((entry for entry in matches if entry["source"] == "ryukomik" and entry["match_score"] >= 90), None)
    if internal:
        status = "ryukomik_project"
    elif confidence >= 90:
        gap = (raw_latest or 0) - (indo_latest or 0)
        status = "lagging" if raw_latest and indo_latest is not None and gap >= 3 else "available"
    elif confidence >= 75:
        status = "ambiguous"
    else:
        status = "untranslated"
    return {
        "primary": primary, "matches": matches, "status": status,
        "confidence": confidence, "raw_latest_chapter": raw_latest,
        "indonesia_latest_chapter": indo_latest,
        "chapter_gap": max(0, (raw_latest or 0) - (indo_latest or 0)) if raw_latest else None,
    }


async def setup_scout_tables() -> None:
    db = await db_module.get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS scout_titles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_title TEXT NOT NULL,
                normalized_title TEXT NOT NULL UNIQUE,
                cover_url TEXT,
                synopsis TEXT,
                genres TEXT NOT NULL DEFAULT '[]',
                content_type TEXT,
                publication_status TEXT,
                scout_status TEXT NOT NULL,
                confidence INTEGER NOT NULL DEFAULT 0,
                raw_latest_chapter REAL,
                indonesia_latest_chapter REAL,
                chapter_gap REAL,
                first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                reviewed_at DATETIME,
                reviewed_by TEXT,
                ignored_until DATETIME,
                ignore_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS scout_source_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scout_title_id INTEGER NOT NULL,
                source_group TEXT NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT,
                slug TEXT,
                title TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                alternative_titles TEXT NOT NULL DEFAULT '[]',
                detail_url TEXT,
                cover_url TEXT,
                synopsis TEXT,
                genres TEXT NOT NULL DEFAULT '[]',
                latest_chapter REAL,
                chapter_count INTEGER,
                match_score INTEGER NOT NULL DEFAULT 0,
                scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scout_title_id,source,source_id)
            );
            CREATE TABLE IF NOT EXISTS scout_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scout_title_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT,
                score INTEGER NOT NULL,
                match_status TEXT NOT NULL,
                UNIQUE(scout_title_id,source,source_id)
            );
            CREATE TABLE IF NOT EXISTS scout_scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_type TEXT NOT NULL,
                query TEXT,
                source TEXT,
                status TEXT NOT NULL,
                titles_checked INTEGER DEFAULT 0,
                matches_found INTEGER DEFAULT 0,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                finished_at DATETIME,
                error_summary TEXT
            );
            CREATE TABLE IF NOT EXISTS scout_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scout_title_id INTEGER NOT NULL,
                admin_id TEXT NOT NULL,
                action TEXT NOT NULL,
                before_data TEXT,
                after_data TEXT,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_scout_status_scan ON scout_titles(scout_status,last_scanned_at DESC);
            CREATE TABLE IF NOT EXISTS raw_chapter_watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scout_title_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                manga_title TEXT NOT NULL,
                last_seen_chapter REAL,
                last_notified_chapter REAL,
                last_notified_at DATETIME,
                notification_message_id TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scout_title_id, source, source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_raw_watch_title ON raw_chapter_watches(scout_title_id, source);
        """)
        await db.commit()
    finally:
        await db.close()


async def _cached(normalized: str) -> Optional[dict[str, Any]]:
    db = await db_module.get_db()
    try:
        row = await (await db.execute(
            "SELECT id,last_scanned_at FROM scout_titles WHERE normalized_title=?", (normalized,)
        )).fetchone()
        if not row or not row["last_scanned_at"]:
            return None
        scanned = datetime.fromisoformat(str(row["last_scanned_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        return await get_scout_title(int(row["id"])) if scanned >= datetime.utcnow() - timedelta(hours=CACHE_HOURS) else None
    finally:
        await db.close()


async def scan_title(query: str, raw_source: str = "all", *, force: bool = False) -> dict[str, Any]:
    query = " ".join(query.split()).strip()
    if len(query) < 2 or len(query) > 180:
        raise ValueError("Judul harus terdiri dari 2–180 karakter.")
    normalized = normalize_title(query)
    if not force:
        cached = await _cached(normalized)
        if cached:
            cached["cached"] = True
            return cached
    raw_entries, indonesia_entries, local_entries = await asyncio.gather(
        _search_raw(query, raw_source), _search_indonesian(query), _local_projects(query)
    )
    if not raw_entries:
        raise ValueError("Judul tidak ditemukan pada sumber RAW yang dipilih.")
    result = _classify(raw_entries, [*indonesia_entries, *local_entries])
    primary = result["primary"]
    db = await db_module.get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        existing = await (await db.execute(
            "SELECT id,scout_status FROM scout_titles WHERE normalized_title=?", (normalize_title(primary["title"]),)
        )).fetchone()
        effective_status = (
            existing["scout_status"]
            if existing and existing["scout_status"] in {"candidate", "adopted", "ignored"}
            else result["status"]
        )
        if existing:
            scout_id = int(existing["id"])
            await db.execute(
                """UPDATE scout_titles SET canonical_title=?,cover_url=?,synopsis=?,genres=?,content_type=?,
                   publication_status=?,scout_status=?,confidence=?,raw_latest_chapter=?,
                   indonesia_latest_chapter=?,chapter_gap=?,last_scanned_at=CURRENT_TIMESTAMP WHERE id=?""",
                (primary["title"], primary.get("cover_url"), primary.get("synopsis"), _json(primary.get("genres", [])),
                 primary.get("content_type"), primary.get("publication_status"), effective_status, result["confidence"],
                 result["raw_latest_chapter"], result["indonesia_latest_chapter"], result["chapter_gap"], scout_id),
            )
            await db.execute("DELETE FROM scout_source_entries WHERE scout_title_id=?", (scout_id,))
            await db.execute("DELETE FROM scout_matches WHERE scout_title_id=?", (scout_id,))
        else:
            cursor = await db.execute(
                """INSERT INTO scout_titles(canonical_title,normalized_title,cover_url,synopsis,genres,
                   content_type,publication_status,scout_status,confidence,raw_latest_chapter,
                   indonesia_latest_chapter,chapter_gap) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (primary["title"], normalize_title(primary["title"]), primary.get("cover_url"), primary.get("synopsis"),
                 _json(primary.get("genres", [])), primary.get("content_type"), primary.get("publication_status"),
                 effective_status, result["confidence"], result["raw_latest_chapter"],
                 result["indonesia_latest_chapter"], result["chapter_gap"]),
            )
            scout_id = int(cursor.lastrowid)
        all_entries = [*raw_entries, *result["matches"]]
        for entry in all_entries:
            await db.execute(
                """INSERT OR REPLACE INTO scout_source_entries
                   (scout_title_id,source_group,source,source_id,slug,title,normalized_title,
                    alternative_titles,detail_url,cover_url,synopsis,genres,latest_chapter,
                    chapter_count,match_score) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (scout_id, entry["source_group"], entry["source"], entry.get("source_id"), entry.get("slug"),
                 entry["title"], entry["normalized_title"], _json(entry.get("alternative_titles", [])),
                 entry.get("detail_url"), entry.get("cover_url"), entry.get("synopsis"), _json(entry.get("genres", [])),
                 entry.get("latest_chapter"), entry.get("chapter_count"), int(entry.get("match_score", 0))),
            )
            if entry["source_group"] != "raw":
                score = int(entry.get("match_score", 0))
                await db.execute(
                    "INSERT OR REPLACE INTO scout_matches(scout_title_id,source,source_id,score,match_status) VALUES(?,?,?,?,?)",
                    (scout_id, entry["source"], entry.get("source_id"), score,
                     "matched" if score >= 90 else "ambiguous" if score >= 75 else "different"),
                )
        await db.execute(
            """INSERT INTO scout_scan_runs(scan_type,query,source,status,titles_checked,matches_found,finished_at)
               VALUES('manual',?,?, 'completed',1,?,CURRENT_TIMESTAMP)""",
            (query, raw_source, sum(entry.get("match_score", 0) >= 75 for entry in result["matches"])),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
    detail = await get_scout_title(scout_id)
    detail["cached"] = False
    return detail


def _title_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["genres"] = _loads(item.get("genres"), [])
    return item


async def list_scout_titles(status: str = "", search: str = "", page: int = 1, page_size: int = 20) -> dict[str, Any]:
    clauses, params = [], []
    if status:
        clauses.append("scout_status=?")
        params.append(status)
    if search:
        clauses.append("(canonical_title LIKE ? OR normalized_title LIKE ?)")
        params.extend([f"%{search}%", f"%{normalize_title(search)}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    db = await db_module.get_db()
    try:
        total = (await (await db.execute(f"SELECT COUNT(*) FROM scout_titles {where}", params)).fetchone())[0]
        rows = await (await db.execute(
            f"SELECT * FROM scout_titles {where} ORDER BY last_scanned_at DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )).fetchall()
    finally:
        await db.close()
    return {
        "items": [_title_row(row) for row in rows], "page": page, "page_size": page_size,
        "total": total, "total_pages": max(1, (total + page_size - 1) // page_size),
    }


async def get_scout_title(scout_id: int) -> Optional[dict[str, Any]]:
    db = await db_module.get_db()
    try:
        row = await (await db.execute("SELECT * FROM scout_titles WHERE id=?", (scout_id,))).fetchone()
        if not row:
            return None
        entries = await (await db.execute(
            "SELECT * FROM scout_source_entries WHERE scout_title_id=? ORDER BY source_group DESC,match_score DESC,source",
            (scout_id,),
        )).fetchall()
    finally:
        await db.close()
    result = _title_row(row)
    result["sources"] = []
    for entry in entries:
        item = dict(entry)
        item["alternative_titles"] = _loads(item.get("alternative_titles"), [])
        item["genres"] = _loads(item.get("genres"), [])
        result["sources"].append(item)
    return result


async def decide(scout_id: int, admin_id: int, action: str, notes: str = "") -> dict[str, Any]:
    mapping = {
        "candidate": "candidate", "adopt": "adopted", "available": "available",
        "ignore": "ignored", "ambiguous": "ambiguous",
    }
    if action not in mapping:
        raise ValueError("Keputusan Project Scout tidak dikenal.")
    db = await db_module.get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        row = await (await db.execute("SELECT * FROM scout_titles WHERE id=?", (scout_id,))).fetchone()
        if not row:
            await db.rollback()
            raise ValueError("Kandidat tidak ditemukan.")
        before = dict(row)
        new_status = mapping[action]
        await db.execute(
            """UPDATE scout_titles SET scout_status=?,reviewed_at=CURRENT_TIMESTAMP,reviewed_by=?,
               ignore_reason=? WHERE id=?""",
            (new_status, str(admin_id), notes if action == "ignore" else None, scout_id),
        )
        await db.execute(
            """INSERT INTO scout_decisions(scout_title_id,admin_id,action,before_data,after_data,notes)
               VALUES(?,?,?,?,?,?)""",
            (scout_id, str(admin_id), action, _json(before), _json({"scout_status": new_status}), notes or None),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
    return await get_scout_title(scout_id)


async def _discover_project_raw(title: str) -> Optional[tuple[str, str]]:
    """Find one best RAW source for a real Ryukomik project title."""
    async def search(source: str) -> tuple[str, Optional[dict[str, Any]]]:
        try:
            rows = await RAW_DOWNLOADERS[source].search_manga(title)
        except Exception:
            return source, None
        best = max(rows, key=lambda item: _title_score(title, str(item.get('title') or '')), default=None)
        return source, best

    found = await asyncio.gather(*(search(source) for source in RAW_DOWNLOADERS))
    ranked = [
        (source, item, _title_score(title, str(item.get('title') or '')))
        for source, item in found if item and item.get('id')
    ]
    ranked = [item for item in ranked if item[2] >= 80]
    if not ranked:
        return None
    source, item, _score = max(ranked, key=lambda entry: entry[2])
    return source, str(item['id'])


async def _active_ryukomik_project_titles() -> set[str]:
    """Read the public Ryukomik catalogue, excluding dropped/cancelled work."""
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        payload = await _request_json(session, PROJECT_CATALOG_URL)
    return {
        normalize_title(str(item.get('title') or ''))
        for item in _catalog_rows(payload)
        if normalize_title(str(item.get('title') or ''))
        and str(item.get('status') or '').casefold() not in {'dropped', 'cancelled'}
    }


async def poll_active_raw_updates() -> list[dict[str, Any]]:
    """Watch only manga that have actually been assigned by Ryukomik.

    Project Scout is deliberately not consulted here. The first observation
    for a task title only establishes a baseline, avoiding historical spam.
    """
    active_titles = await _active_ryukomik_project_titles()
    if not active_titles:
        return []

    db = await db_module.get_db()
    try:
        project_rows = await (await db.execute(
            """SELECT DISTINCT TRIM(manga) AS manga FROM assignments
                 WHERE manga IS NOT NULL AND TRIM(manga) <> ''
                   AND status IN ('claimed','submitted','revision','approved','paid')"""
        )).fetchall()
    finally:
        await db.close()

    events: list[dict[str, Any]] = []
    for project_row in project_rows:
        title = str(project_row['manga'])
        if normalize_title(title) not in active_titles:
            continue
        db = await db_module.get_db()
        try:
            watch = await (await db.execute(
                """SELECT * FROM raw_chapter_watches
                     WHERE scout_title_id=0 AND manga_title=?
                     ORDER BY id DESC LIMIT 1""",
                (title,),
            )).fetchone()
        finally:
            await db.close()

        if watch:
            source, source_id = str(watch['source']), str(watch['source_id'])
        else:
            discovered = await _discover_project_raw(title)
            if not discovered:
                continue
            source, source_id = discovered
            # Title history can have spelling variants while still resolving
            # to one identical source slug. Reuse that technical watch row.
            db = await db_module.get_db()
            try:
                watch = await (await db.execute(
                    """SELECT * FROM raw_chapter_watches
                         WHERE scout_title_id=0 AND source=? AND source_id=?""",
                    (source, source_id),
                )).fetchone()
            finally:
                await db.close()
        try:
            chapters = await get_downloader(source).get_chapter_list(source_id)
        except Exception as error:
            print(f'[RAW WATCH] {source}:{source_id} skipped: {error}')
            continue
        latest = max((
            number for number in (_chapter_number(item.get('title') or item.get('id')) for item in chapters)
            if number is not None
        ), default=None)
        if latest is None:
            continue

        db = await db_module.get_db()
        try:
            if not watch:
                await db.execute(
                    """INSERT INTO raw_chapter_watches
                       (scout_title_id,source,source_id,manga_title,last_seen_chapter,last_notified_chapter)
                       VALUES(0,?,?,?,?,?)""",
                    (source, source_id, title, latest, latest),
                )
            else:
                previous = float(watch['last_notified_chapter'] or watch['last_seen_chapter'] or 0)
                await db.execute(
                    "UPDATE raw_chapter_watches SET last_seen_chapter=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (latest, int(watch['id'])),
                )
                if latest > previous:
                    await db.execute(
                        """UPDATE raw_chapter_watches
                           SET last_notified_chapter=?,last_notified_at=CURRENT_TIMESTAMP WHERE id=?""",
                        (latest, int(watch['id'])),
                    )
                    events.append({'watch_id': int(watch['id']), 'title': title, 'source': source, 'chapter': latest})
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()
    return events


async def record_raw_update_message(watch_id: int, message_id: int) -> None:
    db = await db_module.get_db()
    try:
        await db.execute(
            "UPDATE raw_chapter_watches SET notification_message_id=? WHERE id=?",
            (str(message_id), watch_id),
        )
        await db.commit()
    finally:
        await db.close()

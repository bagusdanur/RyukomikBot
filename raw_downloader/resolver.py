import asyncio
import re
import unicodedata
from difflib import SequenceMatcher

from chapter_utils import normalize_chapter


SOURCE_ORDER = ("asura", "omega", "doujiva")


def normalize_title(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = re.sub(r"['’`]", "", value)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def title_score(query, title):
    query, title = normalize_title(query), normalize_title(title)
    if not query or not title:
        return 0.0
    if query == title:
        return 1.0
    ratio = SequenceMatcher(None, query, title).ratio()
    if query in title or title in query:
        ratio = max(ratio, min(len(query), len(title)) / max(len(query), len(title)))
    return ratio


def filter_allowed_chapters(chapters, allowed):
    indexed = {}
    for chapter in chapters:
        for candidate in (chapter.get("id"), chapter.get("title")):
            normalized = normalize_chapter(str(candidate or ""))
            if normalized:
                indexed.setdefault(normalized, chapter)
    return (
        [indexed[item] for item in allowed if item in indexed],
        [item for item in allowed if item not in indexed],
    )


def _rank_results(query, results):
    ranked = sorted(
        ((title_score(query, item.get("title")), item) for item in results),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return ranked


def _confident_candidate(query, results):
    ranked = _rank_results(query, results)
    if not ranked:
        return None, False
    best_score, best = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0
    exact = best_score == 1.0
    confident = exact or (best_score >= 0.82 and best_score - second_score >= 0.08)
    return best, confident


def deduplicate_results(results_by_source):
    """Return one visible result per normalized title while retaining every source."""
    grouped = {}
    for source in SOURCE_ORDER:
        for item in results_by_source.get(source, []):
            key = normalize_title(item.get("title"))
            if not key:
                continue
            if key not in grouped:
                grouped[key] = {
                    **item,
                    "_source": source,
                    "_sources": [],
                    "_candidates": {},
                }
            grouped[key]["_sources"].append(source)
            grouped[key]["_candidates"][source] = {**item, "_source": source}
    return list(grouped.values())


async def resolve_assignment_raw(title, allowed_chapters, downloaders, progress=None, timeout=12):
    """Resolve a task title and its chapters without requiring a second user click."""

    async def report(message):
        if progress:
            await progress(message)

    async def run():
        active_sources = [source for source in SOURCE_ORDER if source in downloaders]
        if not active_sources:
            return {"status": "not_found", "combined": []}
        await report("Mencari judul di Asura, Omega, dan Doujiva secara bersamaan...")
        searches = await asyncio.gather(
            *(downloaders[source].search_manga(title) for source in active_sources),
            return_exceptions=True,
        )
        results = {}
        candidates = {}
        confident = {}
        for source, response in zip(active_sources, searches):
            result = response if isinstance(response, list) else []
            results[source] = result
            candidates[source], confident[source] = _confident_candidate(title, result)
        combined = deduplicate_results(results)

        available_sources = [
            source
            for source in active_sources
            if candidates[source] and confident[source]
        ]
        if not available_sources:
            return {"status": "ambiguous" if combined else "not_found", "combined": combined}

        await report("Memeriksa kelengkapan chapter tugas pada semua sumber...")

        async def inspect(source):
            candidate = candidates[source]
            try:
                chapters = await downloaders[source].get_chapter_list(str(candidate["id"]))
            except Exception:
                chapters = []
            filtered, missing = filter_allowed_chapters(chapters, allowed_chapters)
            return source, {
                "source": source,
                "manga": candidate,
                "chapters": filtered,
                "missing": missing,
            }

        inspected = await asyncio.gather(*(inspect(source) for source in available_sources))
        coverage = dict(inspected)

        viable = [item for item in coverage.values() if item["chapters"]]
        if not viable:
            return {"status": "chapters_missing", "combined": combined, "coverage": coverage}
        chosen = sorted(
            viable,
            key=lambda item: (-len(item["chapters"]), SOURCE_ORDER.index(item["source"])),
        )[0]
        full_fallbacks = [
            item
            for item in sorted(
                viable,
                key=lambda entry: (-len(entry["chapters"]), SOURCE_ORDER.index(entry["source"])),
            )
            if item["source"] != chosen["source"] and not item["missing"]
        ]
        chosen.update(
            status="resolved",
            combined=combined,
            coverage=coverage,
            fallbacks=full_fallbacks,
        )
        return chosen

    try:
        return await asyncio.wait_for(run(), timeout=timeout)
    except asyncio.TimeoutError:
        return {"status": "timeout", "combined": []}

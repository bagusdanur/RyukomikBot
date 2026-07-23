import asyncio
import re
import unicodedata
from difflib import SequenceMatcher

from chapter_utils import normalize_chapter


SOURCE_ORDER = ("asura", "doujiva")


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


async def resolve_assignment_raw(title, allowed_chapters, downloaders, progress=None, timeout=12):
    """Resolve a task title and its chapters without requiring a second user click."""

    async def report(message):
        if progress:
            await progress(message)

    async def run():
        await report("Mencari judul di Asura dan Doujiva secara bersamaan...")
        searches = await asyncio.gather(
            *(downloaders[source].search_manga(title) for source in SOURCE_ORDER),
            return_exceptions=True,
        )
        results = {}
        combined = []
        candidates = {}
        confident = {}
        for source, response in zip(SOURCE_ORDER, searches):
            result = response if isinstance(response, list) else []
            results[source] = result
            combined.extend({**item, "_source": source} for item in result[:12])
            candidates[source], confident[source] = _confident_candidate(title, result)

        available_sources = [source for source in SOURCE_ORDER if candidates[source] and confident[source]]
        if not available_sources:
            return {"status": "ambiguous" if combined else "not_found", "combined": combined}

        coverage = {}
        for source in available_sources:
            candidate = candidates[source]
            await report(f"Memeriksa chapter tugas di {source.title()}...")
            try:
                chapters = await downloaders[source].get_chapter_list(str(candidate["id"]))
            except Exception:
                chapters = []
            filtered, missing = filter_allowed_chapters(chapters, allowed_chapters)
            coverage[source] = {
                "source": source,
                "manga": candidate,
                "chapters": filtered,
                "missing": missing,
            }
            if source == "asura" and not missing:
                break
            if source == "asura" and "doujiva" in available_sources:
                await report("Chapter Asura belum lengkap, mencoba Doujiva otomatis...")

        viable = [item for item in coverage.values() if item["chapters"]]
        if not viable:
            return {"status": "chapters_missing", "combined": combined, "coverage": coverage}
        chosen = sorted(
            viable,
            key=lambda item: (-len(item["chapters"]), SOURCE_ORDER.index(item["source"])),
        )[0]
        chosen.update(status="resolved", combined=combined)
        return chosen

    try:
        return await asyncio.wait_for(run(), timeout=timeout)
    except asyncio.TimeoutError:
        return {"status": "timeout", "combined": []}

"""RAW workload measurement and pay-rate suggestion, shared by the bot and dashboard.

The scoring in classify_workload()/suggested_rate() is deterministic and has no
network dependency; measure_raw_workload()/suggest_assignment_rate() are the
async pieces that turn a manga+chapter request into a RawWorkload by reading
the actual RAW images, so both callers derive rate purely from RAW difficulty
instead of unrelated heuristics (series popularity, deadline pressure, ...).
"""

import asyncio
from dataclasses import dataclass
from io import BytesIO

import aiohttp
from PIL import Image, UnidentifiedImageError

from raw_downloader.resolver import resolve_assignment_raw


@dataclass(frozen=True)
class RawWorkload:
    page_count: int
    measured_pages: int
    total_height: int
    max_height: int
    tall_pages: int


def classify_workload(workload: RawWorkload) -> tuple[str, int, str]:
    """Return (label, level, human readable reason); level is 0..2.

    Page count is always authoritative. Height data is only used when it was
    actually read, so a temporarily inaccessible image cannot inflate pay.
    """
    page_level = 0 if workload.page_count <= 15 else 1 if workload.page_count <= 25 else 2
    average_height = workload.total_height // workload.measured_pages if workload.measured_pages else 0
    height_level = 0
    if workload.max_height > 16_000 or workload.tall_pages >= 4 or average_height > 10_000:
        height_level = 2
    elif workload.max_height > 8_192 or workload.tall_pages or average_height > 5_500:
        height_level = 1
    level = max(page_level, height_level)
    labels = ("Ringan", "Sedang", "Berat")
    reason = f"{workload.page_count} halaman"
    if workload.measured_pages:
        reason += f", tinggi maks. {workload.max_height:,} px"
        if workload.tall_pages:
            reason += f", {workload.tall_pages} gambar vertikal panjang"
    return labels[level], level, reason


def suggested_rate(minimum: int, maximum: int, workload: RawWorkload) -> int:
    """Suggest conservatively; a single tall page must not jump to max rate."""
    average_height = workload.total_height // workload.measured_pages if workload.measured_pages else 0
    score = 0.0
    if workload.page_count > 15:
        score += 0.20
    if workload.page_count > 20:
        score += 0.16
    if workload.page_count > 25:
        score += 0.20
    if workload.max_height > 8_192:
        score += 0.10
    if workload.tall_pages >= 2:
        score += 0.10
    if average_height > 6_500:
        score += 0.10
    if workload.max_height > 16_000 or average_height > 10_000:
        score += 0.15
    # A short chapter is still short. Even several vertical pages should only
    # nudge its rate, not make it equal to a genuinely long package.
    if workload.page_count <= 15:
        score = min(score, 0.22)
    target = minimum + (maximum - minimum) * min(score, 0.90)
    return max(minimum, min(maximum, int(round(target / 500.0) * 500)))


async def measure_raw_workload(image_urls: list[str], *, session: aiohttp.ClientSession = None, concurrency: int = 8) -> RawWorkload:
    """Range-request each RAW image to read its dimensions; never downloads a full file."""

    async def read_dimensions(client, url, semaphore):
        if not url.startswith(("https://", "http://")):
            return None
        async with semaphore:
            try:
                async with client.get(
                    url,
                    headers={"Range": "bytes=0-524287"},
                    allow_redirects=False,
                ) as response:
                    if response.status not in {200, 206}:
                        return None
                    payload = await response.content.read(524288)
                with Image.open(BytesIO(payload)) as image:
                    return image.width, image.height
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, UnidentifiedImageError):
                return None

    async def measure(client):
        semaphore = asyncio.Semaphore(concurrency)
        return await asyncio.gather(
            *(read_dimensions(client, url, semaphore) for url in image_urls),
            return_exceptions=True,
        )

    if session is not None:
        dimensions = await measure(session)
    else:
        timeout = aiohttp.ClientTimeout(total=18, connect=5, sock_read=8)
        async with aiohttp.ClientSession(timeout=timeout) as owned_session:
            dimensions = await measure(owned_session)

    measured = [item for item in dimensions if isinstance(item, tuple)]
    return RawWorkload(
        page_count=len(image_urls),
        measured_pages=len(measured),
        total_height=sum(item[1] for item in measured),
        max_height=max((item[1] for item in measured), default=0),
        tall_pages=sum(item[1] > 8192 for item in measured),
    )


async def suggest_assignment_rate(
    manga: str,
    chapters: list[str],
    role: str,
    minimum: int,
    maximum: int,
    downloaders: dict,
    *,
    timeout: int = 12,
    progress=None,
) -> dict:
    """Resolve a manga+chapters request against RAW sources and suggest a rate
    driven purely by RAW workload (page count + image height), never above
    the role's existing [minimum, maximum]. Shared by the dashboard and the
    Discord assign flow so both derive the same rate for the same RAW.
    """
    resolved = await resolve_assignment_raw(manga, chapters, downloaders, progress=progress, timeout=timeout)
    status = resolved.get("status")
    if status != "resolved":
        return {"status": status or "not_found"}

    source = resolved["source"]
    downloader = downloaders[source]
    image_sets = await asyncio.gather(
        *(downloader.get_chapter_images(resolved["manga"]["id"], chapter["id"])
          for chapter in resolved["chapters"]),
        return_exceptions=True,
    )
    image_urls = [url for item in image_sets if isinstance(item, list) for url in item]
    if not image_urls:
        return {
            "status": "no_images",
            "source": source,
            "matched_title": resolved["manga"].get("title", manga),
        }

    workload = await measure_raw_workload(image_urls)
    label, level, reason = classify_workload(workload)
    rate_per_chapter = suggested_rate(minimum, maximum, workload)
    return {
        "status": "resolved",
        "source": source,
        "matched_title": resolved["manga"].get("title", manga),
        "chapter_count": len(resolved["chapters"]),
        "page_count": workload.page_count,
        "measured_pages": workload.measured_pages,
        "max_height": workload.max_height,
        "total_height": workload.total_height,
        "tall_pages": workload.tall_pages,
        "workload": label,
        "workload_level": level,
        "reason": reason,
        "rate_per_chapter": rate_per_chapter,
        "minimum_rate": minimum,
        "maximum_rate": maximum,
        "note": "Rekomendasi dapat diubah administrator sebelum tugas dikirim.",
    }

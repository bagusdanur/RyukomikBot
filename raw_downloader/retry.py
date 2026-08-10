import asyncio
import logging
import os
from typing import Any, Callable, Iterable, Optional

import aiohttp

logger = logging.getLogger(__name__)
RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}


async def get_json(
    session,
    url,
    *,
    source,
    stage,
    params=None,
    timeout=30,
    attempts=3,
    validator: Optional[Callable[[Any], bool]] = None,
) -> Any:
    for attempt in range(1, attempts + 1):
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                if response.status == 200:
                    payload = await response.json()
                    if payload and (validator is None or validator(payload)):
                        return payload
                    reason = "empty or malformed response"
                elif response.status in RETRYABLE_STATUSES:
                    reason = f"HTTP {response.status}"
                else:
                    logger.warning("RAW %s %s failed permanently: HTTP %s", source, stage, response.status)
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            reason = type(error).__name__
        logger.warning("RAW %s %s attempt %s/%s failed: %s", source, stage, attempt, attempts, reason)
        if attempt < attempts:
            await asyncio.sleep(0.5 * attempt)
    return None


async def get_bytes(session, url, *, source, stage, timeout=60, attempts=3) -> bytes | None:
    for attempt in range(1, attempts + 1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                if response.status == 200:
                    content = await response.read()
                    if content:
                        return content
                    reason = "empty response"
                elif response.status in RETRYABLE_STATUSES:
                    reason = f"HTTP {response.status}"
                else:
                    logger.warning("RAW %s %s failed permanently: HTTP %s", source, stage, response.status)
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            reason = type(error).__name__
        logger.warning("RAW %s %s attempt %s/%s failed: %s", source, stage, attempt, attempts, reason)
        if attempt < attempts:
            await asyncio.sleep(0.5 * attempt)
    return None


async def download_images(
    session: aiohttp.ClientSession,
    images: Iterable[str],
    chapter_dir: str,
    *,
    source: str,
    extension_for: Callable[[str], str],
    progress: Optional[Callable[[int, int], Any]] = None,
    concurrency: int = 4,
    timeout: float = 25,
    attempts: int = 3,
) -> bool:
    """Download chapter pages concurrently while retaining the API page order."""
    urls = [str(url).strip() for url in images if str(url).strip()]
    if not urls:
        return False
    os.makedirs(chapter_dir, exist_ok=True)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    completed = 0
    progress_lock = asyncio.Lock()

    async def fetch(index: int, url: str) -> bool:
        nonlocal completed
        async with semaphore:
            content = await get_bytes(
                session, url, source=source, stage=f"image:{index:03d}",
                timeout=timeout, attempts=attempts,
            )
        if not content:
            return False
        try:
            with open(os.path.join(chapter_dir, f"{index:03d}.{extension_for(url)}"), "wb") as image_file:
                image_file.write(content)
        except OSError:
            return False
        async with progress_lock:
            completed += 1
            if progress and (completed == len(urls) or completed % 2 == 0):
                result = progress(completed, len(urls))
                if hasattr(result, "__await__"):
                    await result
        return True

    return all(await asyncio.gather(*(fetch(index, url) for index, url in enumerate(urls, 1))))

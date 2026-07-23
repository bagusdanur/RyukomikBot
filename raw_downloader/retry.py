import asyncio
import logging
from typing import Any, Callable, Optional

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

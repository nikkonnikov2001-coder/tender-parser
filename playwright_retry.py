"""Повторные попытки навигации Playwright при сбоях сети/ЕИС."""

from __future__ import annotations

import asyncio
import os


def _goto_retry_count() -> int:
    try:
        n = int(os.getenv("PLAYWRIGHT_GOTO_RETRIES", "3"))
    except ValueError:
        n = 3
    return max(1, min(n, 8))


async def goto_with_retry(
    page,
    url: str,
    *,
    wait_until: str = "domcontentloaded",
    timeout: int = 60_000,
) -> None:
    last_exc: Exception | None = None
    n = _goto_retry_count()
    for attempt in range(1, n + 1):
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout)
            return
        except Exception as e:
            last_exc = e
            print(f"   ⚠️ goto {attempt}/{n} не удалась: {e}")
            if attempt < n:
                await asyncio.sleep(1.5 * attempt)
    assert last_exc is not None
    raise last_exc

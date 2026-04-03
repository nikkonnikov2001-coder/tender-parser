"""Общие настройки Playwright для parser и downloader."""

import os


def playwright_headless() -> bool:
    """PLAYWRIGHT_HEADLESS=0|false|no|off — окно браузера (отладка). По умолчанию headless."""
    raw = os.environ.get("PLAYWRIGHT_HEADLESS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


PLAYWRIGHT_CONTEXT_KWARGS = {
    "viewport": {"width": 1920, "height": 1080},
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "ignore_https_errors": True,
}

"""Общие настройки Playwright для parser и downloader."""

PLAYWRIGHT_CONTEXT_KWARGS = {
    "viewport": {"width": 1920, "height": 1080},
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "ignore_https_errors": True,
}

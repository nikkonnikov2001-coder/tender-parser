"""Подхватывает .env из корня проекта при импорте (безопасно вызывать из любого entrypoint)."""

import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


def build_telegram_proxy_url() -> Optional[str]:
    """Формирует HTTP-прокси URL из переменных окружения TELEGRAM_PROXY_*."""
    host = os.environ.get("TELEGRAM_PROXY_HOST", "").strip()
    port = os.environ.get("TELEGRAM_PROXY_PORT", "").strip()
    user = os.environ.get("TELEGRAM_PROXY_USER", "").strip()
    password = os.environ.get("TELEGRAM_PROXY_PASSWORD", "").strip()
    raw_url = os.environ.get("TELEGRAM_HTTP_PROXY_URL", "").strip()

    if host and port:
        if user or password:
            u = quote(user, safe="")
            p = quote(password, safe="")
            return f"http://{u}:{p}@{host}:{port}"
        return f"http://{host}:{port}"

    return raw_url or None

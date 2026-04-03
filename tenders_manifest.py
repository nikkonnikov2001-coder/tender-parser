"""Снимок метаданных тендеров после поиска — для Excel и повторных прогонов."""

from __future__ import annotations

import json
from pathlib import Path
DEFAULT_MANIFEST_PATH = "tenders_manifest.json"


def write_tenders_manifest(tenders, path: str | Path = DEFAULT_MANIFEST_PATH) -> None:
    """Сохраняет id → url, заголовок и цену с выдачи ЕИС."""
    path = Path(path)
    data: dict[str, dict[str, str]] = {}
    for t in tenders:
        data[t.tender_id] = {
            "url": str(t.url),
            "search_title": t.name,
            "search_price": t.price,
        }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"📝 Манифест тендеров: {path} ({len(data)} шт.)")


def load_tenders_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> dict[str, dict[str, str]]:
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict[str, str]] = {}
    if not isinstance(raw, dict):
        return {}
    for tid, meta in raw.items():
        if not isinstance(meta, dict):
            continue
        out[str(tid)] = {
            "url": str(meta.get("url", "")),
            "search_title": str(meta.get("search_title", "")),
            "search_price": str(meta.get("search_price", "")),
        }
    return out

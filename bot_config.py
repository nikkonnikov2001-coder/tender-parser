"""
Конфигурация бота. Хранит настройки в JSON-файле,
чтобы они сохранялись между перезапусками.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

CONFIG_PATH = "bot_settings.json"

DISTRICT_NAMES = {
    "5277397": "ЦФО",
    "5277341": "СЗФО",
    "5277327": "ПФО",
    "5277331": "СФО",
    "5277336": "УФО",
    "5277321": "ЮФО",
    "5277346": "СКФО",
    "5277351": "ДФО",
}

LAW_NAMES = {
    "fz44": "44-ФЗ",
    "fz223": "223-ФЗ",
    "af": "ПП РФ 615",
}

DATE_FILTER_LABELS = {
    "any":   "Без ограничений",
    "today": "Сегодня",
    "3days": "Последние 3 дня",
    "week":  "Последняя неделя",
    "month": "Последний месяц",
}


@dataclass
class Config:
    # ── Параметры поиска ──────────────────────────────────────
    keywords: str = "организация мероприятий"
    price_from: int = 5_000_000
    price_to: int = 30_000_000
    districts: List[str] = field(
        default_factory=lambda: ["5277331", "5277327"]
    )
    laws: List[str] = field(
        default_factory=lambda: ["fz44", "fz223", "af"]
    )

    # Фильтр по дате публикации
    date_filter: str = "any"

    # Пагинация — сколько карточек на одну «страницу» в чате
    page_size: int = 3

    # ── LLM ───────────────────────────────────────────────────
    ollama_model: str = "qwen2.5:7b"

    # ── Мониторинг ────────────────────────────────────────────
    monitoring_enabled: bool = False
    monitoring_interval_min: int = 60

    # ── История ───────────────────────────────────────────────
    history: List[Dict[str, Any]] = field(default_factory=list)
    seen_tender_ids: List[str] = field(default_factory=list)

    # ── Вычисляемые свойства ──────────────────────────────────

    @property
    def districts_label(self) -> str:
        if not self.districts:
            return "Все"
        return ", ".join(DISTRICT_NAMES.get(d, d) for d in self.districts)

    @property
    def laws_label(self) -> str:
        if not self.laws:
            return "Все"
        return ", ".join(LAW_NAMES.get(k, k) for k in self.laws)

    @property
    def date_filter_label(self) -> str:
        return DATE_FILTER_LABELS.get(self.date_filter, "Без ограничений")

    def get_date_range(self) -> Tuple[Optional[str], Optional[str]]:
        """(date_from, date_to) в формате dd.mm.yyyy или (None, None)."""
        today = datetime.now()
        fmt = "%d.%m.%Y"
        mapping = {
            "today": 0,
            "3days": 3,
            "week":  7,
            "month": 30,
        }
        days = mapping.get(self.date_filter)
        if days is None:
            return None, None
        start = (today - timedelta(days=days)).strftime(fmt)
        end = today.strftime(fmt)
        return start, end

    # ── URL builder ───────────────────────────────────────────

    def build_search_url(self, page: int = 1) -> str:
        from urllib.parse import quote

        parts = [
            "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?",
            f"searchString={quote(self.keywords)}",
            "&morphology=on",
            "&search-filter=Дате+размещения",
            f"&pageNumber={page}",
            "&sortDirection=false",
            "&recordsPerPage=_10",
            "&showLotsInfoHidden=false",
            "&sortBy=UPDATE_DATE",
        ]
        for law in self.laws:
            parts.append(f"&{law}=on")
        parts.append("&currencyIdGeneral=-1")
        parts.append(f"&priceFromGeneral={self.price_from}")
        parts.append(f"&priceToGeneral={self.price_to}")
        if self.districts:
            parts.append(f"&districts={'%2C'.join(self.districts)}")
        date_from, date_to = self.get_date_range()
        if date_from:
            parts.append(f"&publishDateFrom={date_from}")
        if date_to:
            parts.append(f"&publishDateTo={date_to}")
        return "".join(parts)

    # ── Служебные методы ──────────────────────────────────────

    def add_history_entry(self, tenders_found: int, analyzed: int):
        self.history.append({
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "tenders_found": tenders_found,
            "analyzed": analyzed,
        })
        if len(self.history) > 50:
            self.history = self.history[-50:]

    def mark_seen(self, tender_id: str):
        if tender_id not in self.seen_tender_ids:
            self.seen_tender_ids.append(tender_id)
        if len(self.seen_tender_ids) > 500:
            self.seen_tender_ids = self.seen_tender_ids[-500:]

    def is_new_tender(self, tender_id: str) -> bool:
        return tender_id not in self.seen_tender_ids


# ── Чтение / запись ──────────────────────────────────────────

def get_config() -> Config:
    if not os.path.exists(CONFIG_PATH):
        return Config()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Config(**data)
    except Exception:
        return Config()


def save_config(cfg: Config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)

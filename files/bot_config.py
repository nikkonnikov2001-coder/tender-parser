"""
Конфигурация бота. Хранит настройки в JSON-файле,
чтобы они сохранялись между перезапусками.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any

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


@dataclass
class Config:
    # Параметры поиска
    keywords: str = "организация мероприятий"
    price_from: int = 5_000_000
    price_to: int = 30_000_000
    districts: List[str] = field(
        default_factory=lambda: ["5277331", "5277327"]
    )  # СФО + ПФО по умолчанию
    laws: List[str] = field(
        default_factory=lambda: ["fz44", "fz223", "af"]
    )

    # LLM
    ollama_model: str = "qwen2.5:7b"

    # Мониторинг
    monitoring_enabled: bool = False
    monitoring_interval_min: int = 60

    # История
    history: List[Dict[str, Any]] = field(default_factory=list)

    # Кэш ID уже найденных тендеров (для дедупликации при мониторинге)
    seen_tender_ids: List[str] = field(default_factory=list)

    @property
    def districts_label(self) -> str:
        if not self.districts:
            return "Все"
        names = [DISTRICT_NAMES.get(d, d) for d in self.districts]
        return ", ".join(names)

    @property
    def laws_label(self) -> str:
        if not self.laws:
            return "Все"
        names = [LAW_NAMES.get(k, k) for k in self.laws]
        return ", ".join(names)

    def build_search_url(self) -> str:
        """Собирает URL для поиска на zakupki.gov.ru из текущих настроек."""
        from urllib.parse import quote

        parts = [
            "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?",
            f"searchString={quote(self.keywords)}",
            "&morphology=on",
            "&search-filter=Дате+размещения",
            "&pageNumber=1",
            "&sortDirection=false",
            "&recordsPerPage=_10",
            "&showLotsInfoHidden=false",
            "&sortBy=UPDATE_DATE",
        ]

        # Законы
        for law in self.laws:
            parts.append(f"&{law}=on")

        # Валюта и цена
        parts.append("&currencyIdGeneral=-1")
        parts.append(f"&priceFromGeneral={self.price_from}")
        parts.append(f"&priceToGeneral={self.price_to}")

        # Округа
        if self.districts:
            districts_str = "%2C".join(self.districts)
            parts.append(f"&districts={districts_str}")

        return "".join(parts)

    def add_history_entry(self, tenders_found: int, analyzed: int):
        self.history.append({
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "tenders_found": tenders_found,
            "analyzed": analyzed,
        })
        # Храним максимум 50 записей
        if len(self.history) > 50:
            self.history = self.history[-50:]

    def mark_seen(self, tender_id: str):
        if tender_id not in self.seen_tender_ids:
            self.seen_tender_ids.append(tender_id)
        # Храним максимум 500 ID
        if len(self.seen_tender_ids) > 500:
            self.seen_tender_ids = self.seen_tender_ids[-500:]

    def is_new_tender(self, tender_id: str) -> bool:
        return tender_id not in self.seen_tender_ids


def get_config() -> Config:
    """Загрузить конфигурацию из файла (или создать дефолтную)."""
    if not os.path.exists(CONFIG_PATH):
        return Config()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Config(**data)
    except Exception:
        return Config()


def save_config(cfg: Config):
    """Сохранить конфигурацию в файл."""
    data = asdict(cfg)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

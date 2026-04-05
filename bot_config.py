"""
Конфигурация бота. Хранит настройки в JSON-файле,
чтобы они сохранялись между перезапусками.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

CONFIG_DIR = "bot_settings"

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

PLACING_WAY_NAMES = {
    "EA44":  "Электронный аукцион",
    "OK44":  "Открытый конкурс",
    "ZK44":  "Запрос котировок",
    "ZP44":  "Запрос предложений",
    "INM44": "Единственный поставщик",
    "OKASMB44": "Конкурс МСП",
    "EAASMB44": "Аукцион МСП",
}

ORDER_STAGE_NAMES = {
    "AF": "Подача заявок",
    "CA": "Работа комиссии",
    "EF": "Размещение завершено",
    "EC": "Исполнение контракта",
    "IN": "Закупка отменена",
}

SORT_OPTIONS = {
    "UPDATE_DATE":  "По дате обновления",
    "PUBLISH_DATE": "По дате размещения",
    "PRICE_ASC":    "Цена ↑ (по возрастанию)",
    "PRICE_DESC":   "Цена ↓ (по убыванию)",
    "RELEVANCE":    "По релевантности",
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

    # Заказчик (название или ИНН)
    customer_title: str = ""

    # Способ определения поставщика (пустой = все)
    placing_ways: List[str] = field(default_factory=list)

    # Этап размещения (пустой = все)
    order_stages: List[str] = field(default_factory=list)

    # Сортировка
    sort_by: str = "UPDATE_DATE"

    # Сколько страниц ЕИС обходить (1–10)
    max_pages: int = 1

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

    @property
    def placing_ways_label(self) -> str:
        if not self.placing_ways:
            return "Все"
        return ", ".join(PLACING_WAY_NAMES.get(k, k) for k in self.placing_ways)

    @property
    def order_stages_label(self) -> str:
        if not self.order_stages:
            return "Все"
        return ", ".join(ORDER_STAGE_NAMES.get(k, k) for k in self.order_stages)

    @property
    def sort_label(self) -> str:
        return SORT_OPTIONS.get(self.sort_by, "По дате обновления")

    @property
    def customer_label(self) -> str:
        return self.customer_title if self.customer_title else "Не задан"

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
        from eis_config import build_eis_url

        sort_key = self.sort_by
        if sort_key == "PRICE_ASC":
            real_sort, direction = "PRICE", "true"
        elif sort_key == "PRICE_DESC":
            real_sort, direction = "PRICE", "false"
        else:
            real_sort, direction = sort_key, "false"

        date_from, date_to = self.get_date_range()

        return build_eis_url(
            search_query=self.keywords,
            page_number=page,
            records_per_page="_10",
            sort_by=real_sort,
            sort_direction=direction,
            laws=self.laws,
            price_from=self.price_from,
            price_to=self.price_to,
            districts=",".join(self.districts) if self.districts else "",
            date_from=date_from,
            date_to=date_to,
            customer_title=self.customer_title,
            placing_ways=self.placing_ways or None,
            order_stages=self.order_stages or None,
        )

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


# ── Чтение / запись (per-user) ────────────────────────────────

def _user_config_path(chat_id: int) -> str:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    return os.path.join(CONFIG_DIR, f"{chat_id}.json")


def get_config(chat_id: int) -> Config:
    path = _user_config_path(chat_id)
    if not os.path.exists(path):
        return Config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Config(**data)
    except Exception:
        return Config()


def save_config(cfg: Config, chat_id: int):
    path = _user_config_path(chat_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)


def iter_all_user_ids():
    """Возвращает chat_id всех пользователей с сохранёнными конфигами."""
    if not os.path.isdir(CONFIG_DIR):
        return
    for fname in os.listdir(CONFIG_DIR):
        if fname.endswith(".json") and fname != "allowed_users.json":
            try:
                yield int(fname.replace(".json", ""))
            except ValueError:
                pass


# ── Allowlist ─────────────────────────────────────────────────

_ALLOWED_USERS_PATH = os.path.join(CONFIG_DIR, "allowed_users.json")


def get_allowed_users() -> List[int]:
    if not os.path.exists(_ALLOWED_USERS_PATH):
        return []
    try:
        with open(_ALLOWED_USERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [int(uid) for uid in data]
    except Exception:
        return []


def _save_allowed_users(users: List[int]):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(_ALLOWED_USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f)


def add_allowed_user(user_id: int):
    users = get_allowed_users()
    if user_id not in users:
        users.append(user_id)
        _save_allowed_users(users)


def remove_allowed_user(user_id: int) -> bool:
    users = get_allowed_users()
    if user_id in users:
        users.remove(user_id)
        _save_allowed_users(users)
        return True
    return False

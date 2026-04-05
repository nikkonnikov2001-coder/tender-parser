"""
Telegram-бот для мониторинга тендеров ЕИС.
v3: мульти-страницы, shared browser, дедуп мониторинга.
"""

import asyncio
import json
import os
import logging
import math
from datetime import datetime
from typing import Dict, List

from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardButton, InlineKeyboardMarkup,
    TelegramObject,
)
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from load_env import build_telegram_proxy_url  # noqa: F401 (side-effect: loads .env)

from bot_config import (
    Config, get_config, save_config, iter_all_user_ids,
    DATE_FILTER_LABELS, PLACING_WAY_NAMES, ORDER_STAGE_NAMES, SORT_OPTIONS,
    get_allowed_users, add_allowed_user, remove_allowed_user,
)
from bot_search import run_search_pipeline, cleanup_old_files

# ── Логирование ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tender_bot")

# ── Инициализация ────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


_proxy_url = build_telegram_proxy_url()
_session = AiohttpSession(proxy=_proxy_url) if _proxy_url else None

if _proxy_url:
    log.info("Telegram API через прокси: %s:%s",
             os.environ.get("TELEGRAM_PROXY_HOST", ""),
             os.environ.get("TELEGRAM_PROXY_PORT", ""))

bot = Bot(
    token=BOT_TOKEN,
    session=_session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
router = Router()
dp.include_router(router)

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

_CACHE_DIR = "cache"
_results_cache: Dict[int, List[dict]] = {}
waiting_for: Dict[int, str] = {}


def _cache_path(chat_id: int) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{chat_id}_results.json")


def _save_results_cache(chat_id: int, tenders: list):
    _results_cache[chat_id] = tenders
    try:
        with open(_cache_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(tenders, f, ensure_ascii=False)
    except Exception:
        pass


def _load_results_cache(chat_id: int) -> list:
    if chat_id in _results_cache:
        return _results_cache[chat_id]
    path = _cache_path(chat_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _results_cache[chat_id] = data
        return data
    except Exception:
        return []

# ── Контроль доступа ─────────────────────────────────────────

ADMIN_ID: int = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID.isdigit() else 0
ACCESS_MODE = os.environ.get("BOT_ACCESS_MODE", "allowlist").strip().lower()


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID and ADMIN_ID != 0


def is_user_allowed(user_id: int) -> bool:
    if ACCESS_MODE == "open":
        return True
    if is_admin(user_id):
        return True
    return user_id in get_allowed_users()


class AccessControlMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if is_user_allowed(user.id):
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(
                "⛔ <b>Доступ ограничен</b>\n\n"
                f"Ваш ID: <code>{user.id}</code>\n\n"
                "Отправьте этот ID администратору бота,\n"
                "чтобы получить доступ.",
            )
        elif isinstance(event, CallbackQuery):
            await event.answer("⛔ Нет доступа к боту", show_alert=True)


dp.message.middleware(AccessControlMiddleware())
dp.callback_query.middleware(AccessControlMiddleware())


# ══════════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════

def main_menu_kb(chat_id: int = 0) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id) if chat_id else Config()
    mi = "🟢" if cfg.monitoring_enabled else "🔴"
    rows = [
        [
            InlineKeyboardButton(text="🔍 Найти тендеры", callback_data="search"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
        ],
        [
            InlineKeyboardButton(text=f"{mi} Мониторинг", callback_data="monitoring"),
            InlineKeyboardButton(text="📂 История", callback_data="history"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="help"),
        ],
    ]
    if is_admin(chat_id):
        rows.append([
            InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _truncate(text: str, max_len: int = 25) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def settings_kb(chat_id: int) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔑 Запрос: {_truncate(cfg.keywords)}",
            callback_data="set_keywords",
        )],
        [InlineKeyboardButton(
            text=f"💰 Цена: {cfg.price_from / 1e6:.0f}–{cfg.price_to / 1e6:.0f} млн ₽",
            callback_data="set_price",
        )],
        [InlineKeyboardButton(
            text=f"🏢 Заказчик: {_truncate(cfg.customer_label)}",
            callback_data="set_customer",
        )],
        [InlineKeyboardButton(
            text=f"🗺 Регионы: {_truncate(cfg.districts_label)}",
            callback_data="set_districts",
        )],
        [InlineKeyboardButton(
            text=f"📜 Законы: {_truncate(cfg.laws_label)}",
            callback_data="set_laws",
        )],
        [InlineKeyboardButton(
            text=f"🛒 Способ: {_truncate(cfg.placing_ways_label)}",
            callback_data="set_placing",
        )],
        [InlineKeyboardButton(
            text=f"📋 Этап: {_truncate(cfg.order_stages_label)}",
            callback_data="set_stages",
        )],
        [InlineKeyboardButton(
            text=f"📅 Дата: {cfg.date_filter_label}",
            callback_data="set_date",
        )],
        [InlineKeyboardButton(
            text=f"🔃 Сортировка: {_truncate(cfg.sort_label)}",
            callback_data="set_sort",
        )],
        [InlineKeyboardButton(
            text=f"📄 Страниц ЕИС: {cfg.max_pages}",
            callback_data="set_pages",
        )],
        [InlineKeyboardButton(
            text=f"🤖 Модель: {cfg.ollama_model}",
            callback_data="set_model",
        )],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
    ])


def pages_kb(chat_id: int) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id)
    buttons = []
    for n in (1, 2, 3, 5, 10):
        mark = "●" if cfg.max_pages == n else "○"
        buttons.append(InlineKeyboardButton(
            text=f"{mark} {n}", callback_data=f"pages_{n}",
        ))
    return InlineKeyboardMarkup(inline_keyboard=[
        buttons[:3],
        buttons[3:],
        [InlineKeyboardButton(text="✔️ Готово", callback_data="settings")],
    ])


def date_filter_kb(chat_id: int) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id)
    buttons = []
    for key, label in DATE_FILTER_LABELS.items():
        mark = "●" if cfg.date_filter == key else "○"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {label}",
            callback_data=f"date_{key}",
        )])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def districts_kb(chat_id: int) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id)
    districts = {
        "5277397": "ЦФО", "5277341": "СЗФО", "5277327": "ПФО",
        "5277331": "СФО", "5277336": "УФО", "5277321": "ЮФО",
        "5277346": "СКФО", "5277351": "ДФО",
    }
    buttons = []
    for code, name in districts.items():
        mark = "✅" if code in cfg.districts else "⬜"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {name}", callback_data=f"dist_{code}",
        )])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def laws_kb(chat_id: int) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id)
    laws = {"fz44": "44-ФЗ", "fz223": "223-ФЗ", "af": "ПП РФ 615"}
    buttons = []
    for key, name in laws.items():
        mark = "✅" if key in cfg.laws else "⬜"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {name}", callback_data=f"law_{key}",
        )])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def placing_ways_kb(chat_id: int) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id)
    buttons = []
    for code, name in PLACING_WAY_NAMES.items():
        mark = "✅" if code in cfg.placing_ways else "⬜"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {name}", callback_data=f"pw_{code}",
        )])
    buttons.append([InlineKeyboardButton(text="🗑 Сбросить все", callback_data="pw_clear")])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def order_stages_kb(chat_id: int) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id)
    buttons = []
    for code, name in ORDER_STAGE_NAMES.items():
        mark = "✅" if code in cfg.order_stages else "⬜"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {name}", callback_data=f"os_{code}",
        )])
    buttons.append([InlineKeyboardButton(text="🗑 Сбросить все", callback_data="os_clear")])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def sort_kb(chat_id: int) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id)
    buttons = []
    for key, label in SORT_OPTIONS.items():
        mark = "●" if cfg.sort_by == key else "○"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {label}", callback_data=f"sort_{key}",
        )])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def monitoring_kb(chat_id: int) -> InlineKeyboardMarkup:
    cfg = get_config(chat_id)
    toggle = "Выключить" if cfg.monitoring_enabled else "Включить"
    st = "🟢 ВКЛ" if cfg.monitoring_enabled else "🔴 ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Статус: {st}  →  {toggle}", callback_data="monitor_toggle",
        )],
        [
            InlineKeyboardButton(text="⏱ 30 мин", callback_data="mon_30"),
            InlineKeyboardButton(text="⏱ 1 час", callback_data="mon_60"),
        ],
        [
            InlineKeyboardButton(text="⏱ 3 часа", callback_data="mon_180"),
            InlineKeyboardButton(text="⏱ 6 часов", callback_data="mon_360"),
        ],
        [InlineKeyboardButton(
            text=f"Текущий интервал: {cfg.monitoring_interval_min} мин",
            callback_data="noop",
        )],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
    ])


def page_nav_kb(
    page: int, total_pages: int, extra_rows: list | None = None,
) -> InlineKeyboardMarkup:
    buttons = []
    if extra_rows:
        buttons.extend(extra_rows)
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"page_{page - 1}"))
    row.append(InlineKeyboardButton(
        text=f"📄 {page + 1} / {total_pages}", callback_data="noop",
    ))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"page_{page + 1}"))
    buttons.append(row)
    buttons.append([
        InlineKeyboardButton(text="📊 Excel-отчёт", callback_data="send_excel"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_kb(target: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=target)],
    ])


# ══════════════════════════════════════════════════════════════
#  ФОРМАТИРОВАНИЕ КАРТОЧКИ ТЕНДЕРА
# ══════════════════════════════════════════════════════════════

def format_price(raw: str) -> str:
    cleaned = raw.replace(",00", "").replace("₽", "").strip()
    return f"{cleaned} ₽"


def format_tender_card(t: dict, index: int, total: int) -> str:
    name = t.get("name", "—")
    if len(name) > 180:
        name = name[:177] + "..."

    price = format_price(t.get("price", "—"))

    try:
        price_num = float(
            t.get("price", "0")
            .replace(" ", "").replace("\xa0", "")
            .replace(",", ".").replace("₽", "")
        )
        if price_num >= 20_000_000:
            price_icon = "🔴"
        elif price_num >= 10_000_000:
            price_icon = "🟠"
        else:
            price_icon = "🟢"
    except (ValueError, TypeError):
        price_icon = "💰"

    lines = [
        f"{'━' * 28}",
        f"📌  <b>Тендер {index}/{total}</b>",
        f"{'━' * 28}",
        "",
        f"🆔  <code>{t.get('id', '—')}</code>",
        "",
        f"📝  {name}",
        "",
        f"{price_icon}  <b>{price}</b>",
    ]

    if t.get("pub_date") and t["pub_date"] != "—":
        lines.append(f"📅  {t['pub_date']}")

    if t.get("org_name") and t["org_name"] != "—":
        org = t["org_name"]
        if len(org) > 80:
            org = org[:77] + "..."
        lines.append(f"🏢  <i>{org}</i>")

    if t.get("analysis"):
        analysis = t["analysis"]
        if len(analysis) > 350:
            analysis = analysis[:347] + "..."
        lines.append("")
        lines.append(f"{'─' * 28}")
        lines.append("🤖 <b>AI-сводка:</b>")
        lines.append(f"<i>{analysis}</i>")

    return "\n".join(lines)


def format_page(tenders: list, page: int, page_size: int) -> str:
    total = len(tenders)
    start = page * page_size
    end = min(start + page_size, total)
    page_tenders = tenders[start:end]

    cards = []
    for i, t in enumerate(page_tenders):
        card = format_tender_card(t, start + i + 1, total)
        cards.append(card)

    header = (
        f"🔍 <b>Результаты поиска</b>  —  "
        f"найдено <b>{total}</b> тендеров\n"
    )
    return header + "\n\n".join(cards)


def page_tender_buttons(tenders: list, page: int, page_size: int) -> list:
    """Кнопки «AI-подробнее» для тендеров на текущей странице."""
    start = page * page_size
    end = min(start + page_size, len(tenders))
    buttons = []
    for t in tenders[start:end]:
        if t.get("analysis"):
            buttons.append([InlineKeyboardButton(
                text=f"🤖 AI-подробнее: {t.get('id', '?')}",
                callback_data=f"ai_{t['id']}",
            )])
    return buttons


# ══════════════════════════════════════════════════════════════
#  ОБРАБОТЧИКИ
# ══════════════════════════════════════════════════════════════

WELCOME_TEXT = """
<b>🏛 Тендерный AI-ассистент</b>

Автоматический мониторинг и AI-анализ
государственных закупок на <b>zakupki.gov.ru</b>

<b>Возможности:</b>
• 🔍  Поиск тендеров по параметрам
• 📄  Скачивание и чтение ТЗ
• 🤖  AI-анализ документов (LLM)
• 📊  Выгрузка аналитики в Excel
• ⏰  Автомониторинг по расписанию
• 📬  Мгновенные уведомления о новых

Выберите действие:
"""


@router.message(Command("start"))
async def cmd_start(message: Message):
    cid = message.chat.id
    get_config(cid)  # ensure config file exists for user
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb(cid))


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, reply_markup=back_kb("main_menu"))


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    cid = callback.message.chat.id
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb(cid))
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


HELP_TEXT = """
<b>❓ Справка</b>

<b>Команды:</b>
/start — главное меню
/search — быстрый поиск
/settings — настройки
/monitor — мониторинг
/stats — статистика

<b>Как пользоваться:</b>
1️⃣  Настройте параметры (запрос, цена, округа, даты, страницы)
2️⃣  Нажмите «Найти тендеры»
3️⃣  Бот найдёт, скачает ТЗ, проанализирует нейросетью
4️⃣  Листайте карточки ◀️ ▶️ и скачайте Excel

<b>Мониторинг:</b>
Включите авто-поиск — бот проверяет ЕИС
по расписанию и шлёт <b>только новые</b> тендеры.

<b>Поддерживаемые форматы ТЗ:</b>
.docx, .doc, .pdf, .rtf
"""


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await callback.message.edit_text(HELP_TEXT, reply_markup=back_kb())
    await callback.answer()


# ── Настройки ─────────────────────────────────────────────────

@router.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery):
    cid = callback.message.chat.id
    await callback.message.edit_text(
        "<b>⚙️ Настройки поиска</b>\n\nНажмите на параметр, чтобы изменить:",
        reply_markup=settings_kb(cid),
    )
    await callback.answer()


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    cid = message.chat.id
    await message.answer(
        "<b>⚙️ Настройки поиска</b>\n\nНажмите на параметр, чтобы изменить:",
        reply_markup=settings_kb(cid),
    )


@router.callback_query(F.data == "set_keywords")
async def cb_set_keywords(callback: CallbackQuery):
    cid = callback.message.chat.id
    waiting_for[cid] = "keywords"
    cfg = get_config(cid)
    await callback.message.edit_text(
        "<b>🔑 Ключевые слова</b>\n\n"
        f"Текущее: <code>{cfg.keywords}</code>\n\n"
        "Введите новый поисковый запрос.\n\n"
        "Примеры:\n"
        "• <code>организация мероприятий</code>\n"
        "• <code>поставка оборудования</code>\n"
        "• <code>ремонт дорог</code>",
        reply_markup=back_kb("settings"),
    )
    await callback.answer()


@router.callback_query(F.data == "set_price")
async def cb_set_price(callback: CallbackQuery):
    cid = callback.message.chat.id
    waiting_for[cid] = "price"
    cfg = get_config(cid)
    await callback.message.edit_text(
        "<b>💰 Ценовой диапазон</b>\n\n"
        f"Текущий: {cfg.price_from / 1e6:.1f}–{cfg.price_to / 1e6:.1f} млн ₽\n\n"
        "Введите два числа через пробел (в миллионах):\n"
        "<code>5 30</code>  →  от 5 до 30 млн ₽",
        reply_markup=back_kb("settings"),
    )
    await callback.answer()


@router.callback_query(F.data == "set_model")
async def cb_set_model(callback: CallbackQuery):
    cid = callback.message.chat.id
    waiting_for[cid] = "model"
    cfg = get_config(cid)
    await callback.message.edit_text(
        "<b>🤖 Модель LLM (Ollama)</b>\n\n"
        f"Текущая: <code>{cfg.ollama_model}</code>\n\n"
        "Введите название модели:\n"
        "• <code>qwen2.5:7b</code> — быстрая\n"
        "• <code>qwen2.5:14b</code> — точнее\n"
        "• <code>llama3:8b</code>\n"
        "• <code>mistral:7b</code>",
        reply_markup=back_kb("settings"),
    )
    await callback.answer()


# ── Настройки: кол-во страниц ─────────────────────────────────

@router.callback_query(F.data == "set_pages")
async def cb_set_pages(callback: CallbackQuery):
    cid = callback.message.chat.id
    cfg = get_config(cid)
    await callback.message.edit_text(
        "<b>📄 Количество страниц ЕИС</b>\n\n"
        f"Текущее: <b>{cfg.max_pages}</b>\n\n"
        "Каждая страница = ~10 тендеров.\n"
        "Больше страниц = больше результатов, но дольше.",
        reply_markup=pages_kb(cid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pages_"))
async def cb_toggle_pages(callback: CallbackQuery):
    cid = callback.message.chat.id
    n = int(callback.data.replace("pages_", ""))
    cfg = get_config(cid)
    cfg.max_pages = n
    save_config(cfg, cid)
    await callback.message.edit_reply_markup(reply_markup=pages_kb(cid))
    await callback.answer(f"📄 Страниц: {n}")


# ── Настройки: фильтр по дате ─────────────────────────────────

@router.callback_query(F.data == "set_date")
async def cb_set_date(callback: CallbackQuery):
    cid = callback.message.chat.id
    await callback.message.edit_text(
        "<b>📅 Фильтр по дате публикации</b>\n\n"
        "Выберите период, за который искать тендеры:",
        reply_markup=date_filter_kb(cid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("date_"))
async def cb_toggle_date(callback: CallbackQuery):
    cid = callback.message.chat.id
    key = callback.data.replace("date_", "")
    cfg = get_config(cid)
    cfg.date_filter = key
    save_config(cfg, cid)
    await callback.message.edit_reply_markup(reply_markup=date_filter_kb(cid))
    await callback.answer(f"📅 {DATE_FILTER_LABELS.get(key, key)}")


# ── Настройки: регионы ────────────────────────────────────────

@router.callback_query(F.data == "set_districts")
async def cb_set_districts(callback: CallbackQuery):
    cid = callback.message.chat.id
    await callback.message.edit_text(
        "<b>🗺 Федеральные округа</b>\n\nВыберите регионы для поиска:",
        reply_markup=districts_kb(cid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dist_"))
async def cb_toggle_district(callback: CallbackQuery):
    cid = callback.message.chat.id
    code = callback.data.replace("dist_", "")
    cfg = get_config(cid)
    if code in cfg.districts:
        cfg.districts.remove(code)
    else:
        cfg.districts.append(code)
    save_config(cfg, cid)
    await callback.message.edit_reply_markup(reply_markup=districts_kb(cid))
    await callback.answer()


# ── Настройки: законы ─────────────────────────────────────────

@router.callback_query(F.data == "set_laws")
async def cb_set_laws(callback: CallbackQuery):
    cid = callback.message.chat.id
    await callback.message.edit_text(
        "<b>📜 Федеральные законы</b>\n\nВыберите, по каким законам искать:",
        reply_markup=laws_kb(cid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("law_"))
async def cb_toggle_law(callback: CallbackQuery):
    cid = callback.message.chat.id
    key = callback.data.replace("law_", "")
    cfg = get_config(cid)
    if key in cfg.laws:
        cfg.laws.remove(key)
    else:
        cfg.laws.append(key)
    save_config(cfg, cid)
    await callback.message.edit_reply_markup(reply_markup=laws_kb(cid))
    await callback.answer()


# ── Настройки: заказчик ───────────────────────────────────────

@router.callback_query(F.data == "set_customer")
async def cb_set_customer(callback: CallbackQuery):
    cid = callback.message.chat.id
    waiting_for[cid] = "customer"
    cfg = get_config(cid)
    cur = cfg.customer_title or "<i>не задан</i>"
    await callback.message.edit_text(
        "<b>🏢 Заказчик</b>\n\n"
        f"Текущий: {cur}\n\n"
        "Введите название организации или ИНН заказчика.\n"
        "Отправьте <code>-</code> чтобы сбросить фильтр.\n\n"
        "Примеры:\n"
        "• <code>Минобороны</code>\n"
        "• <code>7710168360</code>\n"
        "• <code>Администрация г. Москвы</code>",
        reply_markup=back_kb("settings"),
    )
    await callback.answer()


# ── Настройки: способ закупки ─────────────────────────────────

@router.callback_query(F.data == "set_placing")
async def cb_set_placing(callback: CallbackQuery):
    cid = callback.message.chat.id
    await callback.message.edit_text(
        "<b>🛒 Способ определения поставщика</b>\n\n"
        "Выберите нужные способы закупки.\n"
        "Если ничего не выбрано — ищутся все способы.",
        reply_markup=placing_ways_kb(cid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pw_"))
async def cb_toggle_placing(callback: CallbackQuery):
    cid = callback.message.chat.id
    code = callback.data.replace("pw_", "")
    cfg = get_config(cid)

    if code == "clear":
        cfg.placing_ways = []
    elif code in cfg.placing_ways:
        cfg.placing_ways.remove(code)
    else:
        cfg.placing_ways.append(code)

    save_config(cfg, cid)
    await callback.message.edit_reply_markup(reply_markup=placing_ways_kb(cid))
    await callback.answer()


# ── Настройки: этап размещения ────────────────────────────────

@router.callback_query(F.data == "set_stages")
async def cb_set_stages(callback: CallbackQuery):
    cid = callback.message.chat.id
    await callback.message.edit_text(
        "<b>📋 Этап размещения</b>\n\n"
        "Выберите нужные этапы.\n"
        "Если ничего не выбрано — ищутся все этапы.",
        reply_markup=order_stages_kb(cid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("os_"))
async def cb_toggle_stage(callback: CallbackQuery):
    cid = callback.message.chat.id
    code = callback.data.replace("os_", "")
    cfg = get_config(cid)

    if code == "clear":
        cfg.order_stages = []
    elif code in cfg.order_stages:
        cfg.order_stages.remove(code)
    else:
        cfg.order_stages.append(code)

    save_config(cfg, cid)
    await callback.message.edit_reply_markup(reply_markup=order_stages_kb(cid))
    await callback.answer()


# ── Настройки: сортировка ─────────────────────────────────────

@router.callback_query(F.data == "set_sort")
async def cb_set_sort(callback: CallbackQuery):
    cid = callback.message.chat.id
    await callback.message.edit_text(
        "<b>🔃 Сортировка результатов</b>\n\n"
        "Выберите порядок сортировки:",
        reply_markup=sort_kb(cid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sort_"))
async def cb_toggle_sort(callback: CallbackQuery):
    cid = callback.message.chat.id
    key = callback.data.replace("sort_", "")
    cfg = get_config(cid)
    cfg.sort_by = key
    save_config(cfg, cid)
    await callback.message.edit_reply_markup(reply_markup=sort_kb(cid))
    await callback.answer(f"🔃 {SORT_OPTIONS.get(key, key)}")


# ── Обработка текстовых вводов ────────────────────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_input(message: Message):
    cid = message.chat.id
    field = waiting_for.pop(cid, None)

    if field is None:
        await message.answer(
            "Нажмите /start для главного меню.",
            reply_markup=main_menu_kb(cid),
        )
        return

    cfg = get_config(cid)

    if field == "keywords":
        cfg.keywords = message.text.strip()
        save_config(cfg, cid)
        await message.answer(
            f"✅ Запрос обновлён:\n<code>{cfg.keywords}</code>",
            reply_markup=settings_kb(cid),
        )

    elif field == "price":
        try:
            parts = message.text.strip().replace(",", ".").split()
            cfg.price_from = int(float(parts[0]) * 1_000_000)
            cfg.price_to = int(float(parts[1]) * 1_000_000)
            save_config(cfg, cid)
            await message.answer(
                f"✅ Цена: {cfg.price_from / 1e6:.1f}–{cfg.price_to / 1e6:.1f} млн ₽",
                reply_markup=settings_kb(cid),
            )
        except (ValueError, IndexError):
            await message.answer(
                "❌ Формат: два числа через пробел, например <code>5 30</code>",
                reply_markup=back_kb("settings"),
            )

    elif field == "admin_add":
        if not is_admin(cid):
            return
        try:
            uid = int(message.text.strip())
        except ValueError:
            await message.answer(
                "❌ ID должен быть числом. Попробуйте ещё раз.",
                reply_markup=back_kb("admin_users"),
            )
            return
        add_allowed_user(uid)
        await message.answer(
            f"✅ Пользователь <code>{uid}</code> добавлен.",
            reply_markup=_admin_users_kb(),
        )
        return

    elif field == "customer":
        val = message.text.strip()
        cfg.customer_title = "" if val == "-" else val
        save_config(cfg, cid)
        if cfg.customer_title:
            await message.answer(
                f"✅ Заказчик: <code>{cfg.customer_title}</code>",
                reply_markup=settings_kb(cid),
            )
        else:
            await message.answer(
                "✅ Фильтр по заказчику сброшен.",
                reply_markup=settings_kb(cid),
            )

    elif field == "model":
        cfg.ollama_model = message.text.strip()
        save_config(cfg, cid)
        await message.answer(
            f"✅ Модель: <code>{cfg.ollama_model}</code>",
            reply_markup=settings_kb(cid),
        )


# ══════════════════════════════════════════════════════════════
#  ПОИСК  +  ПАГИНАЦИЯ
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "search")
async def cb_search(callback: CallbackQuery):
    await callback.answer("🚀 Запускаю поиск...")
    await run_full_search(callback.message.chat.id)


@router.message(Command("search"))
async def cmd_search(message: Message):
    await run_full_search(message.chat.id)


async def run_full_search(chat_id: int):
    cfg = get_config(chat_id)

    filter_lines = [
        f"🔑  <code>{cfg.keywords}</code>",
        f"💰  {cfg.price_from / 1e6:.0f}–{cfg.price_to / 1e6:.0f} млн ₽",
        f"🗺  {cfg.districts_label}",
        f"📜  {cfg.laws_label}",
        f"📅  {cfg.date_filter_label}",
    ]
    if cfg.customer_title:
        filter_lines.append(f"🏢  {cfg.customer_title}")
    if cfg.placing_ways:
        filter_lines.append(f"🛒  {cfg.placing_ways_label}")
    if cfg.order_stages:
        filter_lines.append(f"📋  {cfg.order_stages_label}")
    filter_lines.append(f"📄  Страниц: {cfg.max_pages}")

    status_msg = await bot.send_message(
        chat_id,
        "⏳ <b>Поиск тендеров...</b>\n\n"
        + "\n".join(filter_lines)
        + "\n\n▪️ Этап 1/4 — Поиск на zakupki.gov.ru...",
    )

    try:
        result = await run_search_pipeline(cfg, bot, chat_id, status_msg)
    except Exception as e:
        log.exception("Ошибка поиска")
        await status_msg.edit_text(
            f"❌ <b>Ошибка при поиске</b>\n\n<code>{e}</code>",
            reply_markup=back_kb(),
        )
        return

    if not result or not result.get("tenders"):
        await status_msg.edit_text(
            "🔍 <b>Тендеры не найдены</b>\n\n"
            "Попробуйте изменить параметры поиска\n"
            "или расширить фильтр по дате.",
            reply_markup=main_menu_kb(chat_id),
        )
        return

    tenders = result["tenders"]
    _save_results_cache(chat_id, tenders)

    total_pages = math.ceil(len(tenders) / cfg.page_size)
    text = format_page(tenders, 0, cfg.page_size)
    ai_btns = page_tender_buttons(tenders, 0, cfg.page_size)
    await bot.send_message(
        chat_id, text,
        reply_markup=page_nav_kb(0, total_pages, extra_rows=ai_btns),
        disable_web_page_preview=True,
    )

    await bot.send_message(
        chat_id,
        f"✅ <b>Поиск завершён!</b>\n\n"
        f"📌  Найдено: <b>{len(tenders)}</b> тендеров\n"
        f"📄  AI-анализ: <b>{result.get('analyzed', 0)}</b> ТЗ\n"
        f"⏱  Время: {result.get('elapsed', '—')}\n\n"
        f"Листайте карточки кнопками ◀️ ▶️\n"
        f"или скачайте полный Excel-отчёт.",
        reply_markup=main_menu_kb(chat_id),
    )

    cfg = get_config(chat_id)
    cfg.add_history_entry(len(tenders), result.get("analyzed", 0))
    save_config(cfg, chat_id)


# ── Пагинация ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("page_"))
async def cb_page(callback: CallbackQuery):
    page = int(callback.data.replace("page_", ""))
    chat_id = callback.message.chat.id
    tenders = _load_results_cache(chat_id)

    if not tenders:
        await callback.answer("Результаты устарели. Запустите новый поиск.")
        return

    cfg = get_config(chat_id)
    total_pages = math.ceil(len(tenders) / cfg.page_size)
    page = max(0, min(page, total_pages - 1))

    text = format_page(tenders, page, cfg.page_size)
    ai_btns = page_tender_buttons(tenders, page, cfg.page_size)
    await callback.message.edit_text(
        text,
        reply_markup=page_nav_kb(page, total_pages, extra_rows=ai_btns),
        disable_web_page_preview=True,
    )
    await callback.answer()


# ── Отправка Excel ────────────────────────────────────────────

@router.callback_query(F.data == "send_excel")
async def cb_send_excel(callback: CallbackQuery):
    cid = callback.message.chat.id
    excel_path = os.path.join("reports", f"{cid}.xlsx")
    if not os.path.exists(excel_path):
        await callback.answer("Excel-файл ещё не сформирован.")
        return

    doc = FSInputFile(excel_path, filename="Tenders_Analytics_DB.xlsx")
    tenders = _load_results_cache(cid)
    await bot.send_document(
        cid,
        document=doc,
        caption=(
            f"📊 <b>Аналитический отчёт</b>\n\n"
            f"Тендеров: {len(tenders)}\n"
            f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        ),
    )
    await callback.answer("📊 Отчёт отправлен!")


# ── Подробный AI-анализ отдельного тендера ─────────────────────

@router.callback_query(F.data.startswith("ai_"))
async def cb_ai_detail(callback: CallbackQuery):
    tender_id = callback.data.replace("ai_", "")
    chat_id = callback.message.chat.id
    tenders = _load_results_cache(chat_id)

    tender = next((t for t in tenders if t.get("id") == tender_id), None)
    if not tender:
        await callback.answer("Тендер не найден в кэше.")
        return

    analysis = tender.get("analysis", "AI-анализ не выполнен для этого тендера.")

    text = (
        f"🤖 <b>AI-анализ тендера</b>\n\n"
        f"🆔  <code>{tender_id}</code>\n"
        f"{'━' * 28}\n\n"
        f"{analysis}\n\n"
        f"{'━' * 28}"
    )

    if tender.get("url"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔗 Открыть на zakupki.gov.ru", url=tender["url"],
            )],
            [InlineKeyboardButton(text="◀️ К результатам", callback_data="page_0")],
        ])
    else:
        kb = back_kb("page_0")

    await callback.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  МОНИТОРИНГ  (с дедупликацией)
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "monitoring")
async def cb_monitoring(callback: CallbackQuery):
    cid = callback.message.chat.id
    cfg = get_config(cid)
    st = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    seen = len(cfg.seen_tender_ids)
    await callback.message.edit_text(
        f"<b>⏰ Мониторинг тендеров</b>\n\n"
        f"Статус: {st}\n"
        f"Интервал: каждые {cfg.monitoring_interval_min} мин\n"
        f"Следующий запуск: {_next_run_text(cid)}\n"
        f"Известных тендеров: {seen}\n\n"
        f"Бот автоматически проверяет ЕИС\n"
        f"и присылает <b>только новые</b> тендеры.",
        reply_markup=monitoring_kb(cid),
    )
    await callback.answer()


@router.message(Command("monitor"))
async def cmd_monitor(message: Message):
    cid = message.chat.id
    cfg = get_config(cid)
    st = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    await message.answer(
        f"<b>⏰ Мониторинг</b>  —  {st}\n"
        f"Интервал: {cfg.monitoring_interval_min} мин",
        reply_markup=monitoring_kb(cid),
    )


@router.callback_query(F.data == "monitor_toggle")
async def cb_monitor_toggle(callback: CallbackQuery):
    cid = callback.message.chat.id
    cfg = get_config(cid)
    cfg.monitoring_enabled = not cfg.monitoring_enabled
    save_config(cfg, cid)

    if cfg.monitoring_enabled:
        _schedule_monitoring(cid, cfg.monitoring_interval_min)
        await callback.answer("✅ Мониторинг включён!")
    else:
        _remove_monitoring_job(cid)
        await callback.answer("🔴 Мониторинг выключен")

    st = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    await callback.message.edit_text(
        f"<b>⏰ Мониторинг тендеров</b>\n\n"
        f"Статус: {st}\n"
        f"Интервал: каждые {cfg.monitoring_interval_min} мин\n"
        f"Следующий запуск: {_next_run_text(cid)}",
        reply_markup=monitoring_kb(cid),
    )


@router.callback_query(F.data.startswith("mon_"))
async def cb_set_interval(callback: CallbackQuery):
    cid = callback.message.chat.id
    minutes = int(callback.data.replace("mon_", ""))
    cfg = get_config(cid)
    cfg.monitoring_interval_min = minutes
    save_config(cfg, cid)
    if cfg.monitoring_enabled:
        _schedule_monitoring(cid, minutes)
    await callback.answer(f"⏱ Интервал: {minutes} мин")
    st = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    await callback.message.edit_text(
        f"<b>⏰ Мониторинг</b>\n\n"
        f"Статус: {st}\n"
        f"Интервал: каждые {minutes} мин\n"
        f"Следующий запуск: {_next_run_text(cid)}",
        reply_markup=monitoring_kb(cid),
    )


def _monitor_job_id(chat_id: int) -> str:
    return f"monitor_{chat_id}"


def _schedule_monitoring(chat_id: int, interval_min: int):
    _remove_monitoring_job(chat_id)
    scheduler.add_job(
        _monitoring_tick, "interval",
        minutes=interval_min, id=_monitor_job_id(chat_id),
        replace_existing=True,
        kwargs={"chat_id": chat_id},
    )


def _remove_monitoring_job(chat_id: int):
    try:
        scheduler.remove_job(_monitor_job_id(chat_id))
    except Exception:
        pass


async def _monitoring_tick(chat_id: int):
    """Автоматический поиск: находит тендеры, фильтрует новые, отправляет."""
    log.info("⏰ Авто-поиск для chat_id=%s", chat_id)

    cfg = get_config(chat_id)

    status_msg = await bot.send_message(
        chat_id,
        "⏰ <b>Автоматический мониторинг...</b>\n\n"
        f"🔑  <code>{cfg.keywords}</code>\n"
        f"💰  {cfg.price_from / 1e6:.0f}–{cfg.price_to / 1e6:.0f} млн ₽\n"
        f"📄  Страниц: {cfg.max_pages}",
    )

    try:
        result = await run_search_pipeline(cfg, bot, chat_id, status_msg)
    except Exception:
        log.exception("Ошибка авто-поиска для chat_id=%s", chat_id)
        await status_msg.edit_text(
            "❌ <b>Ошибка мониторинга</b>\n\nСледующая попытка по расписанию.",
            reply_markup=main_menu_kb(chat_id),
        )
        return

    if not result or not result.get("tenders"):
        await status_msg.edit_text(
            "⏰ Мониторинг: новых тендеров не найдено.",
            reply_markup=main_menu_kb(chat_id),
        )
        return

    all_tenders = result["tenders"]

    cfg = get_config(chat_id)
    new_tenders = [t for t in all_tenders if cfg.is_new_tender(t["id"])]

    for t in all_tenders:
        cfg.mark_seen(t["id"])
    cfg.add_history_entry(len(all_tenders), result.get("analyzed", 0))
    save_config(cfg, chat_id)

    if not new_tenders:
        await bot.send_message(
            chat_id,
            f"⏰ <b>Мониторинг завершён</b>\n\n"
            f"Найдено {len(all_tenders)} тендеров — все уже известны.\n"
            f"Следующий запуск: {_next_run_text(chat_id)}",
            reply_markup=main_menu_kb(chat_id),
        )
        return

    _save_results_cache(chat_id, new_tenders)

    total_pages = math.ceil(len(new_tenders) / cfg.page_size)
    text = format_page(new_tenders, 0, cfg.page_size)
    ai_btns = page_tender_buttons(new_tenders, 0, cfg.page_size)
    await bot.send_message(
        chat_id, text,
        reply_markup=page_nav_kb(0, total_pages, extra_rows=ai_btns),
        disable_web_page_preview=True,
    )

    await bot.send_message(
        chat_id,
        f"🔔 <b>Мониторинг: новые тендеры!</b>\n\n"
        f"📌  Новых: <b>{len(new_tenders)}</b> (всего найдено {len(all_tenders)})\n"
        f"📄  AI-анализ: <b>{result.get('analyzed', 0)}</b> ТЗ\n"
        f"⏱  Время: {result.get('elapsed', '—')}\n\n"
        f"Следующий запуск: {_next_run_text(chat_id)}",
        reply_markup=main_menu_kb(chat_id),
    )

    excel_path = result.get("excel_path")
    if excel_path and os.path.exists(excel_path):
        doc = FSInputFile(excel_path, filename="Tenders_Analytics_DB.xlsx")
        await bot.send_document(
            chat_id,
            document=doc,
            caption=(
                f"📊 <b>Автоотчёт мониторинга</b>\n"
                f"Новых тендеров: {len(new_tenders)}\n"
                f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            ),
        )


def _next_run_text(chat_id: int) -> str:
    job = scheduler.get_job(_monitor_job_id(chat_id))
    if job and job.next_run_time:
        return job.next_run_time.strftime("%d.%m.%Y %H:%M:%S")
    return "—"


# ══════════════════════════════════════════════════════════════
#  ИСТОРИЯ  +  СТАТИСТИКА
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "history")
async def cb_history(callback: CallbackQuery):
    cfg = get_config(callback.message.chat.id)
    if not cfg.history:
        text = "<b>📂 История поисков</b>\n\nПока пусто — запустите первый поиск!"
    else:
        lines = []
        for e in cfg.history[-10:]:
            lines.append(
                f"  {e['date']}  │  "
                f"📌 {e['tenders_found']}  "
                f"📄 {e['analyzed']}"
            )
        text = (
            f"<b>📂 История поисков</b>\n"
            f"<i>Последние {len(lines)}:</i>\n\n"
            f"<code>{'─' * 34}\n"
            f"  Дата              │ Тендеры\n"
            f"{'─' * 34}\n"
            + "\n".join(lines) + "\n"
            f"{'─' * 34}</code>"
        )
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    cid = callback.message.chat.id
    cfg = get_config(cid)
    total_s = len(cfg.history)
    total_t = sum(e.get("tenders_found", 0) for e in cfg.history)
    total_a = sum(e.get("analyzed", 0) for e in cfg.history)
    mon = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Выключен"

    text = (
        "<b>📊 Статистика</b>\n\n"
        f"🔍  Всего поисков: <b>{total_s}</b>\n"
        f"📌  Найдено тендеров: <b>{total_t}</b>\n"
        f"📄  Проанализировано ТЗ: <b>{total_a}</b>\n"
        f"🗂  Известных ID: <b>{len(cfg.seen_tender_ids)}</b>\n\n"
        f"<b>Мониторинг:</b>  {mon}\n"
        f"<b>Интервал:</b>  {cfg.monitoring_interval_min} мин\n\n"
        f"{'━' * 28}\n"
        f"<b>Текущие фильтры:</b>\n"
        f"🔑  {cfg.keywords}\n"
        f"💰  {cfg.price_from / 1e6:.0f}–{cfg.price_to / 1e6:.0f} млн ₽\n"
        f"🏢  {cfg.customer_label}\n"
        f"📅  {cfg.date_filter_label}\n"
        f"🗺  {cfg.districts_label}\n"
        f"📜  {cfg.laws_label}\n"
        f"🛒  {cfg.placing_ways_label}\n"
        f"📋  {cfg.order_stages_label}\n"
        f"🔃  {cfg.sort_label}\n"
        f"📄  Страниц: {cfg.max_pages}"
    )
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    cid = message.chat.id
    cfg = get_config(cid)
    total = len(cfg.history)
    tenders = sum(e.get("tenders_found", 0) for e in cfg.history)
    await message.answer(
        f"<b>📊</b>  Поисков: {total}  │  Тендеров: {tenders}",
        reply_markup=main_menu_kb(cid),
    )


# ══════════════════════════════════════════════════════════════
#  АДМИН: УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ
# ══════════════════════════════════════════════════════════════

def _admin_users_text() -> str:
    users = get_allowed_users()
    mode = "🔓 Открытый" if ACCESS_MODE == "open" else "🔒 По allowlist"
    lines = [
        f"<b>👥 Управление пользователями</b>\n",
        f"Режим доступа: <b>{mode}</b>",
        f"Админ: <code>{ADMIN_ID}</code>\n",
    ]
    if users:
        lines.append(f"<b>Разрешённые ({len(users)}):</b>")
        for uid in users:
            lines.append(f"  • <code>{uid}</code>")
    else:
        lines.append("<i>Список пуст — доступ только у админа.</i>")
    lines.append(
        "\n<b>Команды:</b>\n"
        "/allow <code>ID</code> — добавить пользователя\n"
        "/deny <code>ID</code> — удалить пользователя"
    )
    return "\n".join(lines)


def _admin_users_kb() -> InlineKeyboardMarkup:
    users = get_allowed_users()
    rows = []
    for uid in users:
        rows.append([InlineKeyboardButton(
            text=f"❌ Удалить {uid}",
            callback_data=f"deny_{uid}",
        )])
    rows.append([InlineKeyboardButton(
        text="➕ Добавить пользователя",
        callback_data="admin_add_user",
    )])
    rows.append([InlineKeyboardButton(
        text="◀️ Главное меню", callback_data="main_menu",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin_users")
async def cb_admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Только для администратора", show_alert=True)
        return
    await callback.message.edit_text(
        _admin_users_text(),
        reply_markup=_admin_users_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_add_user")
async def cb_admin_add_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Только для администратора", show_alert=True)
        return
    cid = callback.message.chat.id
    waiting_for[cid] = "admin_add"
    await callback.message.edit_text(
        "<b>➕ Добавление пользователя</b>\n\n"
        "Введите Telegram ID пользователя (число).\n\n"
        "Пользователь может узнать свой ID,\n"
        "отправив /start этому боту.",
        reply_markup=back_kb("admin_users"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("deny_"))
async def cb_deny_inline(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Только для администратора", show_alert=True)
        return
    uid_str = callback.data.replace("deny_", "")
    try:
        uid = int(uid_str)
    except ValueError:
        await callback.answer("❌ Неверный ID")
        return

    if remove_allowed_user(uid):
        await callback.answer(f"✅ Пользователь {uid} удалён")
    else:
        await callback.answer(f"Пользователь {uid} не найден в списке")

    await callback.message.edit_text(
        _admin_users_text(),
        reply_markup=_admin_users_kb(),
    )


@router.message(Command("allow"))
async def cmd_allow(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer(
            "Использование: /allow <code>USER_ID</code>",
            reply_markup=back_kb("admin_users"),
        )
        return

    try:
        uid = int(command.args.strip())
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return

    add_allowed_user(uid)
    await message.answer(
        f"✅ Пользователь <code>{uid}</code> добавлен в allowlist.",
        reply_markup=_admin_users_kb(),
    )


@router.message(Command("deny"))
async def cmd_deny(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return

    if not command.args:
        await message.answer(
            "Использование: /deny <code>USER_ID</code>",
            reply_markup=back_kb("admin_users"),
        )
        return

    try:
        uid = int(command.args.strip())
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return

    if remove_allowed_user(uid):
        await message.answer(
            f"✅ Пользователь <code>{uid}</code> удалён из allowlist.",
            reply_markup=_admin_users_kb(),
        )
    else:
        await message.answer(
            f"Пользователь <code>{uid}</code> не найден в списке.",
            reply_markup=_admin_users_kb(),
        )


@router.message(Command("users"))
async def cmd_users(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(_admin_users_text(), reply_markup=_admin_users_kb())


# ══════════════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════════════

async def main():
    log.info("🚀 Запуск Тендерного AI-бота v5 (multi-user + allowlist)...")
    log.info("🔐 Режим доступа: %s | Админ: %s | Разрешённых: %d",
             ACCESS_MODE, ADMIN_ID, len(get_allowed_users()))

    cleanup_old_files()

    for uid in iter_all_user_ids():
        cfg = get_config(uid)
        if cfg.monitoring_enabled:
            _schedule_monitoring(uid, cfg.monitoring_interval_min)
            log.info("♻️ Мониторинг восстановлен для %s: %d мин",
                     uid, cfg.monitoring_interval_min)

    scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())

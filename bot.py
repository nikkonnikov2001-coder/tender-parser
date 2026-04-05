"""
Telegram-бот для мониторинга тендеров ЕИС.
v2: красивые карточки, пагинация, фильтры по дате.
"""

import asyncio
import os
import logging
import math
from datetime import datetime
from typing import Dict, List

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, FSInputFile,
    InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import load_env  # noqa: F401

from bot_config import (
    Config, get_config, save_config,
    DATE_FILTER_LABELS,
)
from bot_search import run_search_pipeline

# ── Логирование ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tender_bot")

# ── Инициализация ────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
router = Router()
dp.include_router(router)

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# ── Хранилище результатов для пагинации (chat_id → list) ─────
_results_cache: Dict[int, List[dict]] = {}

# ── Хранилище «ожидаем текстовый ввод» ───────────────────────
waiting_for: Dict[int, str] = {}


# ══════════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════

def main_menu_kb() -> InlineKeyboardMarkup:
    cfg = get_config()
    mi = "🟢" if cfg.monitoring_enabled else "🔴"
    return InlineKeyboardMarkup(inline_keyboard=[
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
    ])


def settings_kb() -> InlineKeyboardMarkup:
    cfg = get_config()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔑 Запрос: {cfg.keywords}",
            callback_data="set_keywords",
        )],
        [InlineKeyboardButton(
            text=f"💰 Цена: {cfg.price_from / 1e6:.0f}–{cfg.price_to / 1e6:.0f} млн ₽",
            callback_data="set_price",
        )],
        [InlineKeyboardButton(
            text=f"🗺 Регионы: {cfg.districts_label}",
            callback_data="set_districts",
        )],
        [InlineKeyboardButton(
            text=f"📜 Законы: {cfg.laws_label}",
            callback_data="set_laws",
        )],
        [InlineKeyboardButton(
            text=f"📅 Дата: {cfg.date_filter_label}",
            callback_data="set_date",
        )],
        [InlineKeyboardButton(
            text=f"🤖 Модель: {cfg.ollama_model}",
            callback_data="set_model",
        )],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
    ])


def date_filter_kb() -> InlineKeyboardMarkup:
    cfg = get_config()
    buttons = []
    for key, label in DATE_FILTER_LABELS.items():
        mark = "●" if cfg.date_filter == key else "○"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {label}",
            callback_data=f"date_{key}",
        )])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def districts_kb() -> InlineKeyboardMarkup:
    cfg = get_config()
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


def laws_kb() -> InlineKeyboardMarkup:
    cfg = get_config()
    laws = {"fz44": "44-ФЗ", "fz223": "223-ФЗ", "af": "ПП РФ 615"}
    buttons = []
    for key, name in laws.items():
        mark = "✅" if key in cfg.laws else "⬜"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {name}", callback_data=f"law_{key}",
        )])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def monitoring_kb() -> InlineKeyboardMarkup:
    cfg = get_config()
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


def page_nav_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Клавиатура пагинации ◀ страница ▶"""
    buttons = []
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


def tender_card_kb(tender_url: str, tender_id: str) -> InlineKeyboardMarkup:
    """Кнопки под отдельной карточкой тендера."""
    buttons = []
    if tender_url:
        buttons.append([InlineKeyboardButton(
            text="🔗 Открыть на zakupki.gov.ru",
            url=tender_url,
        )])
    buttons.append([InlineKeyboardButton(
        text="🤖 Подробный AI-анализ",
        callback_data=f"ai_{tender_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_kb(target: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=target)],
    ])


# ══════════════════════════════════════════════════════════════
#  ФОРМАТИРОВАНИЕ КАРТОЧКИ ТЕНДЕРА
# ══════════════════════════════════════════════════════════════

def format_price(raw: str) -> str:
    """5 000 000,00  →  5 000 000 ₽"""
    cleaned = raw.replace(",00", "").replace("₽", "").strip()
    # Оставляем пробелы-разделители
    return f"{cleaned} ₽"


def format_tender_card(t: dict, index: int, total: int) -> str:
    """Красивая карточка тендера."""

    name = t.get("name", "—")
    if len(name) > 180:
        name = name[:177] + "..."

    price = format_price(t.get("price", "—"))

    # Определяем иконку по цене
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

    # AI-анализ (короткая версия)
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
    """Форматирует страницу с несколькими карточками."""
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
• 📬  Мгновенные уведомления

Выберите действие:
"""


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, reply_markup=back_kb())


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())
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
1️⃣  Настройте параметры (запрос, цена, округа, даты)
2️⃣  Нажмите «Найти тендеры»
3️⃣  Бот найдёт, скачает ТЗ, проанализирует нейросетью
4️⃣  Листайте карточки ◀️ ▶️ и скачайте Excel

<b>Мониторинг:</b>
Включите авто-поиск — бот проверяет ЕИС
по расписанию и шлёт новые тендеры.
"""


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await callback.message.edit_text(HELP_TEXT, reply_markup=back_kb())
    await callback.answer()


# ── Настройки ─────────────────────────────────────────────────

@router.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>⚙️ Настройки поиска</b>\n\nНажмите на параметр, чтобы изменить:",
        reply_markup=settings_kb(),
    )
    await callback.answer()


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await message.answer(
        "<b>⚙️ Настройки поиска</b>\n\nНажмите на параметр, чтобы изменить:",
        reply_markup=settings_kb(),
    )


# ── Настройки: ключевые слова ─────────────────────────────────

@router.callback_query(F.data == "set_keywords")
async def cb_set_keywords(callback: CallbackQuery):
    waiting_for[callback.message.chat.id] = "keywords"
    cfg = get_config()
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
    waiting_for[callback.message.chat.id] = "price"
    cfg = get_config()
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
    waiting_for[callback.message.chat.id] = "model"
    cfg = get_config()
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


# ── Настройки: фильтр по дате ─────────────────────────────────

@router.callback_query(F.data == "set_date")
async def cb_set_date(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>📅 Фильтр по дате публикации</b>\n\n"
        "Выберите период, за который искать тендеры:",
        reply_markup=date_filter_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("date_"))
async def cb_toggle_date(callback: CallbackQuery):
    key = callback.data.replace("date_", "")
    cfg = get_config()
    cfg.date_filter = key
    save_config(cfg)
    await callback.message.edit_reply_markup(reply_markup=date_filter_kb())
    await callback.answer(f"📅 {DATE_FILTER_LABELS.get(key, key)}")


# ── Настройки: регионы ────────────────────────────────────────

@router.callback_query(F.data == "set_districts")
async def cb_set_districts(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>🗺 Федеральные округа</b>\n\nВыберите регионы для поиска:",
        reply_markup=districts_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dist_"))
async def cb_toggle_district(callback: CallbackQuery):
    code = callback.data.replace("dist_", "")
    cfg = get_config()
    if code in cfg.districts:
        cfg.districts.remove(code)
    else:
        cfg.districts.append(code)
    save_config(cfg)
    await callback.message.edit_reply_markup(reply_markup=districts_kb())
    await callback.answer()


# ── Настройки: законы ─────────────────────────────────────────

@router.callback_query(F.data == "set_laws")
async def cb_set_laws(callback: CallbackQuery):
    await callback.message.edit_text(
        "<b>📜 Федеральные законы</b>\n\nВыберите, по каким законам искать:",
        reply_markup=laws_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("law_"))
async def cb_toggle_law(callback: CallbackQuery):
    key = callback.data.replace("law_", "")
    cfg = get_config()
    if key in cfg.laws:
        cfg.laws.remove(key)
    else:
        cfg.laws.append(key)
    save_config(cfg)
    await callback.message.edit_reply_markup(reply_markup=laws_kb())
    await callback.answer()


# ── Обработка текстовых вводов ────────────────────────────────

@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_input(message: Message):
    chat_id = message.chat.id
    field = waiting_for.pop(chat_id, None)

    if field is None:
        await message.answer(
            "Нажмите /start для главного меню.",
            reply_markup=main_menu_kb(),
        )
        return

    cfg = get_config()

    if field == "keywords":
        cfg.keywords = message.text.strip()
        save_config(cfg)
        await message.answer(
            f"✅ Запрос обновлён:\n<code>{cfg.keywords}</code>",
            reply_markup=settings_kb(),
        )

    elif field == "price":
        try:
            parts = message.text.strip().replace(",", ".").split()
            cfg.price_from = int(float(parts[0]) * 1_000_000)
            cfg.price_to = int(float(parts[1]) * 1_000_000)
            save_config(cfg)
            await message.answer(
                f"✅ Цена: {cfg.price_from / 1e6:.1f}–{cfg.price_to / 1e6:.1f} млн ₽",
                reply_markup=settings_kb(),
            )
        except (ValueError, IndexError):
            await message.answer(
                "❌ Формат: два числа через пробел, например <code>5 30</code>",
                reply_markup=back_kb("settings"),
            )

    elif field == "model":
        cfg.ollama_model = message.text.strip()
        save_config(cfg)
        await message.answer(
            f"✅ Модель: <code>{cfg.ollama_model}</code>",
            reply_markup=settings_kb(),
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
    cfg = get_config()

    status_msg = await bot.send_message(
        chat_id,
        "⏳ <b>Поиск тендеров...</b>\n\n"
        f"🔑  <code>{cfg.keywords}</code>\n"
        f"💰  {cfg.price_from / 1e6:.0f}–{cfg.price_to / 1e6:.0f} млн ₽\n"
        f"🗺  {cfg.districts_label}\n"
        f"📅  {cfg.date_filter_label}\n"
        f"📜  {cfg.laws_label}\n\n"
        "▪️ Этап 1/4 — Поиск на zakupki.gov.ru...",
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
            reply_markup=main_menu_kb(),
        )
        return

    tenders = result["tenders"]
    _results_cache[chat_id] = tenders

    # Показываем первую страницу
    total_pages = math.ceil(len(tenders) / cfg.page_size)
    text = format_page(tenders, 0, cfg.page_size)
    await bot.send_message(
        chat_id, text,
        reply_markup=page_nav_kb(0, total_pages),
        disable_web_page_preview=True,
    )

    # Итог
    await bot.send_message(
        chat_id,
        f"✅ <b>Поиск завершён!</b>\n\n"
        f"📌  Найдено: <b>{len(tenders)}</b> тендеров\n"
        f"📄  AI-анализ: <b>{result.get('analyzed', 0)}</b> ТЗ\n"
        f"⏱  Время: {result.get('elapsed', '—')}\n\n"
        f"Листайте карточки кнопками ◀️ ▶️\n"
        f"или скачайте полный Excel-отчёт.",
        reply_markup=main_menu_kb(),
    )

    # Сохраняем историю
    cfg = get_config()
    cfg.add_history_entry(len(tenders), result.get("analyzed", 0))
    save_config(cfg)


# ── Пагинация ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("page_"))
async def cb_page(callback: CallbackQuery):
    page = int(callback.data.replace("page_", ""))
    chat_id = callback.message.chat.id
    tenders = _results_cache.get(chat_id, [])

    if not tenders:
        await callback.answer("Результаты устарели. Запустите новый поиск.")
        return

    cfg = get_config()
    total_pages = math.ceil(len(tenders) / cfg.page_size)
    page = max(0, min(page, total_pages - 1))

    text = format_page(tenders, page, cfg.page_size)
    await callback.message.edit_text(
        text,
        reply_markup=page_nav_kb(page, total_pages),
        disable_web_page_preview=True,
    )
    await callback.answer()


# ── Отправка Excel из кэша ────────────────────────────────────

@router.callback_query(F.data == "send_excel")
async def cb_send_excel(callback: CallbackQuery):
    excel_path = "Tenders_Analytics_DB.xlsx"
    if not os.path.exists(excel_path):
        await callback.answer("Excel-файл ещё не сформирован.")
        return

    doc = FSInputFile(excel_path, filename="Tenders_Analytics_DB.xlsx")
    tenders = _results_cache.get(callback.message.chat.id, [])
    await bot.send_document(
        callback.message.chat.id,
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
    tenders = _results_cache.get(chat_id, [])

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
#  МОНИТОРИНГ
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "monitoring")
async def cb_monitoring(callback: CallbackQuery):
    cfg = get_config()
    st = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    await callback.message.edit_text(
        f"<b>⏰ Мониторинг тендеров</b>\n\n"
        f"Статус: {st}\n"
        f"Интервал: каждые {cfg.monitoring_interval_min} мин\n"
        f"Следующий запуск: {_next_run_text()}\n\n"
        f"Бот автоматически проверяет ЕИС\n"
        f"и присылает новые тендеры.",
        reply_markup=monitoring_kb(),
    )
    await callback.answer()


@router.message(Command("monitor"))
async def cmd_monitor(message: Message):
    cfg = get_config()
    st = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    await message.answer(
        f"<b>⏰ Мониторинг</b>  —  {st}\n"
        f"Интервал: {cfg.monitoring_interval_min} мин",
        reply_markup=monitoring_kb(),
    )


@router.callback_query(F.data == "monitor_toggle")
async def cb_monitor_toggle(callback: CallbackQuery):
    cfg = get_config()
    cfg.monitoring_enabled = not cfg.monitoring_enabled
    save_config(cfg)

    if cfg.monitoring_enabled:
        _schedule_monitoring(cfg.monitoring_interval_min)
        await callback.answer("✅ Мониторинг включён!")
    else:
        _remove_monitoring_job()
        await callback.answer("🔴 Мониторинг выключен")

    st = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    await callback.message.edit_text(
        f"<b>⏰ Мониторинг тендеров</b>\n\n"
        f"Статус: {st}\n"
        f"Интервал: каждые {cfg.monitoring_interval_min} мин\n"
        f"Следующий запуск: {_next_run_text()}",
        reply_markup=monitoring_kb(),
    )


@router.callback_query(F.data.startswith("mon_"))
async def cb_set_interval(callback: CallbackQuery):
    minutes = int(callback.data.replace("mon_", ""))
    cfg = get_config()
    cfg.monitoring_interval_min = minutes
    save_config(cfg)
    if cfg.monitoring_enabled:
        _schedule_monitoring(minutes)
    await callback.answer(f"⏱ Интервал: {minutes} мин")
    st = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    await callback.message.edit_text(
        f"<b>⏰ Мониторинг</b>\n\n"
        f"Статус: {st}\n"
        f"Интервал: каждые {minutes} мин\n"
        f"Следующий запуск: {_next_run_text()}",
        reply_markup=monitoring_kb(),
    )


def _schedule_monitoring(interval_min: int):
    _remove_monitoring_job()
    scheduler.add_job(
        _monitoring_tick, "interval",
        minutes=interval_min, id="tender_monitor",
        replace_existing=True,
    )


def _remove_monitoring_job():
    try:
        scheduler.remove_job("tender_monitor")
    except Exception:
        pass


async def _monitoring_tick():
    if not ADMIN_CHAT_ID:
        return
    log.info("⏰ Автоматический поиск...")
    try:
        await run_full_search(int(ADMIN_CHAT_ID))
    except Exception:
        log.exception("Ошибка авто-поиска")


def _next_run_text() -> str:
    job = scheduler.get_job("tender_monitor")
    if job and job.next_run_time:
        return job.next_run_time.strftime("%d.%m.%Y %H:%M:%S")
    return "—"


# ══════════════════════════════════════════════════════════════
#  ИСТОРИЯ  +  СТАТИСТИКА
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "history")
async def cb_history(callback: CallbackQuery):
    cfg = get_config()
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
    cfg = get_config()
    total_s = len(cfg.history)
    total_t = sum(e.get("tenders_found", 0) for e in cfg.history)
    total_a = sum(e.get("analyzed", 0) for e in cfg.history)
    mon = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Выключен"

    text = (
        "<b>📊 Статистика</b>\n\n"
        f"🔍  Всего поисков: <b>{total_s}</b>\n"
        f"📌  Найдено тендеров: <b>{total_t}</b>\n"
        f"📄  Проанализировано ТЗ: <b>{total_a}</b>\n\n"
        f"<b>Мониторинг:</b>  {mon}\n"
        f"<b>Интервал:</b>  {cfg.monitoring_interval_min} мин\n\n"
        f"{'━' * 28}\n"
        f"<b>Текущие фильтры:</b>\n"
        f"🔑  {cfg.keywords}\n"
        f"💰  {cfg.price_from / 1e6:.0f}–{cfg.price_to / 1e6:.0f} млн ₽\n"
        f"📅  {cfg.date_filter_label}\n"
        f"🗺  {cfg.districts_label}\n"
        f"📜  {cfg.laws_label}"
    )
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    cfg = get_config()
    total = len(cfg.history)
    tenders = sum(e.get("tenders_found", 0) for e in cfg.history)
    await message.answer(
        f"<b>📊</b>  Поисков: {total}  │  Тендеров: {tenders}",
        reply_markup=main_menu_kb(),
    )


# ══════════════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════════════

async def main():
    log.info("🚀 Запуск Тендерного AI-бота v2...")

    cfg = get_config()
    if cfg.monitoring_enabled:
        _schedule_monitoring(cfg.monitoring_interval_min)
        log.info("♻️ Мониторинг восстановлен: %d мин", cfg.monitoring_interval_min)

    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

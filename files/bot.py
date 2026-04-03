"""
Telegram-бот для мониторинга тендеров ЕИС.
Полноценный интерфейс: поиск, настройки, мониторинг, история.
"""

import asyncio
import os
import logging
from datetime import datetime

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

from bot_config import Config, get_config, save_config
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

# ── Клавиатуры ───────────────────────────────────────────────

def main_menu_kb() -> InlineKeyboardMarkup:
    cfg = get_config()
    monitor_icon = "🟢" if cfg.monitoring_enabled else "🔴"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Найти тендеры", callback_data="search"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
        ],
        [
            InlineKeyboardButton(
                text=f"{monitor_icon} Мониторинг",
                callback_data="monitoring",
            ),
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
            text=f"🔑 Ключевые слова: {cfg.keywords}",
            callback_data="set_keywords",
        )],
        [InlineKeyboardButton(
            text=f"💰 Цена: {cfg.price_from / 1_000_000:.0f}–{cfg.price_to / 1_000_000:.0f} млн ₽",
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
            text=f"🤖 Модель LLM: {cfg.ollama_model}",
            callback_data="set_model",
        )],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
    ])


def monitoring_kb() -> InlineKeyboardMarkup:
    cfg = get_config()
    status = "🟢 ВКЛ" if cfg.monitoring_enabled else "🔴 ВЫКЛ"
    toggle_text = "Выключить" if cfg.monitoring_enabled else "Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Статус: {status}  →  {toggle_text}",
            callback_data="monitor_toggle",
        )],
        [
            InlineKeyboardButton(text="⏱ Каждые 30 мин", callback_data="mon_30"),
            InlineKeyboardButton(text="⏱ Каждый 1 час", callback_data="mon_60"),
        ],
        [
            InlineKeyboardButton(text="⏱ Каждые 3 часа", callback_data="mon_180"),
            InlineKeyboardButton(text="⏱ Каждые 6 часов", callback_data="mon_360"),
        ],
        [InlineKeyboardButton(
            text=f"Текущий интервал: {cfg.monitoring_interval_min} мин",
            callback_data="noop",
        )],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
    ])


def districts_kb() -> InlineKeyboardMarkup:
    """Выбор федеральных округов."""
    cfg = get_config()
    districts = {
        "5277397": "ЦФО",
        "5277341": "СЗФО",
        "5277327": "ПФО",
        "5277331": "СФО",
        "5277336": "УФО",
        "5277321": "ЮФО",
        "5277346": "СКФО",
        "5277351": "ДФО",
    }
    buttons = []
    for code, name in districts.items():
        mark = "✅" if code in cfg.districts else "⬜"
        buttons.append([InlineKeyboardButton(
            text=f"{mark} {name}",
            callback_data=f"dist_{code}",
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
            text=f"{mark} {name}",
            callback_data=f"law_{key}",
        )])
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_kb(target: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=target)],
    ])


# ── /start ───────────────────────────────────────────────────

WELCOME_TEXT = """
<b>🏛 Тендерный AI-ассистент</b>

Бот для автоматического мониторинга и анализа
государственных закупок на <b>zakupki.gov.ru</b>

<b>Возможности:</b>
• 🔍  Поиск тендеров по параметрам
• 📄  Скачивание и чтение ТЗ
• 🤖  AI-анализ документов (Ollama LLM)
• 📊  Выгрузка аналитики в Excel
• ⏰  Автоматический мониторинг по расписанию
• 📬  Мгновенные уведомления о новых тендерах

Выберите действие:
"""


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await send_help(message)


# ── Навигация (callback) ─────────────────────────────────────

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await send_help_edit(callback)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


# ── Помощь ────────────────────────────────────────────────────

HELP_TEXT = """
<b>❓ Справка</b>

<b>Команды:</b>
/start — главное меню
/search — быстрый поиск
/settings — настройки
/monitor — управление мониторингом
/stats — статистика
/help — эта справка

<b>Как пользоваться:</b>
1. Настройте параметры поиска (ключевые слова, цена, регионы)
2. Нажмите «Найти тендеры»
3. Бот найдёт тендеры, скачает ТЗ и проанализирует нейросетью
4. Вы получите Excel-отчёт и карточки тендеров прямо в чат

<b>Мониторинг:</b>
Включите автоматический поиск — бот будет проверять
ЕИС по расписанию и присылать новые тендеры.
"""


async def send_help(message: Message):
    await message.answer(HELP_TEXT, reply_markup=back_kb())


async def send_help_edit(callback: CallbackQuery):
    await callback.message.edit_text(HELP_TEXT, reply_markup=back_kb())
    await callback.answer()


# ── Настройки ─────────────────────────────────────────────────

@router.callback_query(F.data == "settings")
async def cb_settings(callback: CallbackQuery):
    cfg = get_config()
    text = (
        "<b>⚙️ Настройки поиска</b>\n\n"
        "Нажмите на параметр, чтобы изменить его:"
    )
    await callback.message.edit_text(text, reply_markup=settings_kb())
    await callback.answer()


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    text = "<b>⚙️ Настройки поиска</b>\n\nНажмите на параметр, чтобы изменить его:"
    await message.answer(text, reply_markup=settings_kb())


# ── Настройки: ключевые слова ─────────────────────────────────

waiting_for = {}  # chat_id -> field_name


@router.callback_query(F.data == "set_keywords")
async def cb_set_keywords(callback: CallbackQuery):
    waiting_for[callback.message.chat.id] = "keywords"
    await callback.message.edit_text(
        "<b>🔑 Ключевые слова</b>\n\n"
        "Введите поисковый запрос.\n"
        "Текущее значение: <code>{}</code>\n\n"
        "Примеры:\n"
        "• <code>организация мероприятий</code>\n"
        "• <code>поставка оборудования</code>\n"
        "• <code>ремонт дорог</code>".format(get_config().keywords),
        reply_markup=back_kb("settings"),
    )
    await callback.answer()


@router.callback_query(F.data == "set_price")
async def cb_set_price(callback: CallbackQuery):
    waiting_for[callback.message.chat.id] = "price"
    cfg = get_config()
    await callback.message.edit_text(
        "<b>💰 Ценовой диапазон</b>\n\n"
        f"Текущий: {cfg.price_from / 1_000_000:.1f}–{cfg.price_to / 1_000_000:.1f} млн ₽\n\n"
        "Введите два числа через пробел (в миллионах):\n"
        "Например: <code>5 30</code>  →  от 5 до 30 млн",
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
        "• <code>qwen2.5:7b</code> (быстрая)\n"
        "• <code>qwen2.5:14b</code> (точнее)\n"
        "• <code>llama3:8b</code>\n"
        "• <code>mistral:7b</code>",
        reply_markup=back_kb("settings"),
    )
    await callback.answer()


# ── Обработка текстовых вводов (настройки) ────────────────────

@router.message(F.text)
async def handle_text_input(message: Message):
    chat_id = message.chat.id
    field = waiting_for.pop(chat_id, None)

    if field is None:
        # Если пользователь просто пишет текст — подсказка
        await message.answer(
            "Используйте /start для главного меню или нажмите кнопку ниже.",
            reply_markup=main_menu_kb(),
        )
        return

    cfg = get_config()

    if field == "keywords":
        cfg.keywords = message.text.strip()
        save_config(cfg)
        await message.answer(
            f"✅ Ключевые слова обновлены:\n<code>{cfg.keywords}</code>",
            reply_markup=settings_kb(),
        )

    elif field == "price":
        try:
            parts = message.text.strip().split()
            price_from = float(parts[0]) * 1_000_000
            price_to = float(parts[1]) * 1_000_000
            cfg.price_from = int(price_from)
            cfg.price_to = int(price_to)
            save_config(cfg)
            await message.answer(
                f"✅ Ценовой диапазон обновлён:\n"
                f"{cfg.price_from / 1_000_000:.1f}–{cfg.price_to / 1_000_000:.1f} млн ₽",
                reply_markup=settings_kb(),
            )
        except (ValueError, IndexError):
            await message.answer(
                "❌ Неверный формат. Введите два числа через пробел:\n"
                "Например: <code>5 30</code>",
                reply_markup=back_kb("settings"),
            )

    elif field == "model":
        cfg.ollama_model = message.text.strip()
        save_config(cfg)
        await message.answer(
            f"✅ Модель обновлена: <code>{cfg.ollama_model}</code>",
            reply_markup=settings_kb(),
        )


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


# ── Поиск ─────────────────────────────────────────────────────

@router.callback_query(F.data == "search")
async def cb_search(callback: CallbackQuery):
    await callback.answer("🚀 Запускаю поиск...")
    await run_full_search(callback.message.chat.id)


@router.message(Command("search"))
async def cmd_search(message: Message):
    await run_full_search(message.chat.id)


async def run_full_search(chat_id: int):
    """Полный цикл: поиск → скачивание → анализ → отчёт."""
    cfg = get_config()

    # ── Шаг 1: статус-сообщение с прогрессом
    status_msg = await bot.send_message(
        chat_id,
        "⏳ <b>Поиск тендеров...</b>\n\n"
        f"🔑 Запрос: <code>{cfg.keywords}</code>\n"
        f"💰 Цена: {cfg.price_from / 1_000_000:.0f}–{cfg.price_to / 1_000_000:.0f} млн ₽\n"
        f"🗺 Округа: {cfg.districts_label}\n"
        f"📜 Законы: {cfg.laws_label}\n\n"
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
            "Попробуйте изменить параметры поиска.",
            reply_markup=main_menu_kb(),
        )
        return

    # ── Шаг 5: отправка карточек тендеров в чат
    tenders = result["tenders"]
    for i, t in enumerate(tenders[:10], 1):
        card = (
            f"<b>📌 Тендер {i}/{len(tenders)}</b>\n\n"
            f"<b>ID:</b> {t.get('id', '—')}\n"
            f"<b>Цена:</b> {t.get('price', '—')}\n"
            f"<b>Название:</b> {t.get('name', '—')[:200]}\n"
        )
        if t.get("analysis"):
            card += f"\n<b>🤖 AI-анализ:</b>\n<i>{t['analysis'][:600]}</i>\n"
        if t.get("url"):
            card += f"\n🔗 <a href=\"{t['url']}\">Открыть на zakupki.gov.ru</a>"

        await bot.send_message(chat_id, card, disable_web_page_preview=True)
        await asyncio.sleep(0.3)

    # ── Шаг 6: Excel-отчёт
    excel_path = result.get("excel_path")
    if excel_path and os.path.exists(excel_path):
        doc = FSInputFile(excel_path, filename="Tenders_Analytics_DB.xlsx")
        await bot.send_document(
            chat_id,
            document=doc,
            caption=(
                f"📊 <b>Аналитический отчёт</b>\n\n"
                f"Найдено тендеров: {len(tenders)}\n"
                f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            ),
        )

    # ── Итоговое сообщение
    await bot.send_message(
        chat_id,
        f"✅ <b>Поиск завершён!</b>\n\n"
        f"📌 Найдено: {len(tenders)} тендеров\n"
        f"📄 Проанализировано ТЗ: {result.get('analyzed', 0)}\n"
        f"⏱ Время: {result.get('elapsed', '—')}",
        reply_markup=main_menu_kb(),
    )

    # Сохраняем в историю
    cfg = get_config()
    cfg.add_history_entry(len(tenders), result.get("analyzed", 0))
    save_config(cfg)


# ── Мониторинг ────────────────────────────────────────────────

@router.callback_query(F.data == "monitoring")
async def cb_monitoring(callback: CallbackQuery):
    cfg = get_config()
    status = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    text = (
        f"<b>⏰ Мониторинг тендеров</b>\n\n"
        f"Статус: {status}\n"
        f"Интервал: каждые {cfg.monitoring_interval_min} мин\n"
        f"Следующий запуск: {_next_run_text()}\n\n"
        f"При включённом мониторинге бот автоматически\n"
        f"проверяет ЕИС и присылает новые тендеры."
    )
    await callback.message.edit_text(text, reply_markup=monitoring_kb())
    await callback.answer()


@router.message(Command("monitor"))
async def cmd_monitor(message: Message):
    cfg = get_config()
    status = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    text = (
        f"<b>⏰ Мониторинг тендеров</b>\n\n"
        f"Статус: {status}\n"
        f"Интервал: каждые {cfg.monitoring_interval_min} мин"
    )
    await message.answer(text, reply_markup=monitoring_kb())


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

    # Обновляем клавиатуру
    status = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    text = (
        f"<b>⏰ Мониторинг тендеров</b>\n\n"
        f"Статус: {status}\n"
        f"Интервал: каждые {cfg.monitoring_interval_min} мин\n"
        f"Следующий запуск: {_next_run_text()}"
    )
    await callback.message.edit_text(text, reply_markup=monitoring_kb())


@router.callback_query(F.data.startswith("mon_"))
async def cb_set_interval(callback: CallbackQuery):
    minutes = int(callback.data.replace("mon_", ""))
    cfg = get_config()
    cfg.monitoring_interval_min = minutes
    save_config(cfg)

    if cfg.monitoring_enabled:
        _schedule_monitoring(minutes)

    await callback.answer(f"⏱ Интервал: {minutes} мин")
    status = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Неактивен"
    text = (
        f"<b>⏰ Мониторинг тендеров</b>\n\n"
        f"Статус: {status}\n"
        f"Интервал: каждые {cfg.monitoring_interval_min} мин\n"
        f"Следующий запуск: {_next_run_text()}"
    )
    await callback.message.edit_text(text, reply_markup=monitoring_kb())


def _schedule_monitoring(interval_min: int):
    _remove_monitoring_job()
    scheduler.add_job(
        _monitoring_tick,
        "interval",
        minutes=interval_min,
        id="tender_monitor",
        replace_existing=True,
    )
    log.info("Мониторинг запланирован: каждые %d мин", interval_min)


def _remove_monitoring_job():
    try:
        scheduler.remove_job("tender_monitor")
    except Exception:
        pass


async def _monitoring_tick():
    """Автоматический запуск поиска по расписанию."""
    if not ADMIN_CHAT_ID:
        return
    log.info("⏰ Автоматический поиск по расписанию...")
    try:
        await run_full_search(int(ADMIN_CHAT_ID))
    except Exception:
        log.exception("Ошибка автоматического поиска")


def _next_run_text() -> str:
    job = scheduler.get_job("tender_monitor")
    if job and job.next_run_time:
        return job.next_run_time.strftime("%d.%m.%Y %H:%M:%S")
    return "—"


# ── История ───────────────────────────────────────────────────

@router.callback_query(F.data == "history")
async def cb_history(callback: CallbackQuery):
    cfg = get_config()
    if not cfg.history:
        text = (
            "<b>📂 История поисков</b>\n\n"
            "Пока нет сохранённых поисков.\n"
            "Запустите первый поиск!"
        )
    else:
        lines = []
        for entry in cfg.history[-10:]:  # последние 10
            lines.append(
                f"• {entry['date']}  —  "
                f"📌 {entry['tenders_found']} тендеров, "
                f"📄 {entry['analyzed']} проанализировано"
            )
        text = (
            "<b>📂 История поисков</b>\n"
            f"<i>Последние {len(lines)} запусков:</i>\n\n"
            + "\n".join(lines)
        )
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


# ── Статистика ────────────────────────────────────────────────

@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    cfg = get_config()
    total_searches = len(cfg.history)
    total_tenders = sum(e.get("tenders_found", 0) for e in cfg.history)
    total_analyzed = sum(e.get("analyzed", 0) for e in cfg.history)

    monitor_status = "🟢 Активен" if cfg.monitoring_enabled else "🔴 Выключен"

    text = (
        "<b>📊 Статистика</b>\n\n"
        f"🔍 Всего поисков: <b>{total_searches}</b>\n"
        f"📌 Всего тендеров найдено: <b>{total_tenders}</b>\n"
        f"📄 Всего ТЗ проанализировано: <b>{total_analyzed}</b>\n\n"
        f"⏰ Мониторинг: {monitor_status}\n"
        f"⏱ Интервал: {cfg.monitoring_interval_min} мин\n\n"
        f"<b>Текущие настройки:</b>\n"
        f"🔑 {cfg.keywords}\n"
        f"💰 {cfg.price_from / 1_000_000:.0f}–{cfg.price_to / 1_000_000:.0f} млн ₽\n"
        f"🗺 {cfg.districts_label}\n"
        f"📜 {cfg.laws_label}"
    )
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    cfg = get_config()
    total_searches = len(cfg.history)
    total_tenders = sum(e.get("tenders_found", 0) for e in cfg.history)
    text = (
        f"<b>📊 Статистика</b>\n\n"
        f"🔍 Поисков: {total_searches}\n"
        f"📌 Тендеров: {total_tenders}"
    )
    await message.answer(text, reply_markup=main_menu_kb())


# ── Запуск ────────────────────────────────────────────────────

async def main():
    log.info("🚀 Запуск Тендерного AI-бота...")

    # Восстанавливаем мониторинг если он был включён
    cfg = get_config()
    if cfg.monitoring_enabled:
        _schedule_monitoring(cfg.monitoring_interval_min)
        log.info("♻️ Мониторинг восстановлен: каждые %d мин", cfg.monitoring_interval_min)

    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

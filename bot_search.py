"""
Поисковый конвейер с прогрессом в Telegram.
Интегрируется с parser/downloader/analyzer,
обновляет статус-сообщение на каждом этапе.
"""

import asyncio
import os
import shutil
import time
import logging
from typing import Dict, Any, Optional

from aiogram import Bot
from aiogram.types import Message

from bot_config import Config

log = logging.getLogger("tender_bot.search")

DOWNLOADS_ROOT = "downloads"
REPORTS_ROOT = "reports"

_CLEANUP_MAX_AGE_DAYS = int(os.environ.get("CLEANUP_MAX_AGE_DAYS", "14"))


def cleanup_old_files(max_age_days: int | None = None):
    """Удаляет папки тендеров и файлы отчётов/кэша старше max_age_days."""
    max_age = max_age_days if max_age_days is not None else _CLEANUP_MAX_AGE_DAYS
    if max_age <= 0:
        return
    cutoff = time.time() - max_age * 86400
    removed = 0

    for root_dir in (DOWNLOADS_ROOT, REPORTS_ROOT, "cache"):
        if not os.path.isdir(root_dir):
            continue
        for entry in os.scandir(root_dir):
            try:
                mtime = entry.stat().st_mtime
                if mtime >= cutoff:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    os.remove(entry.path)
                removed += 1
            except Exception:
                pass

    if removed:
        log.info("Очистка: удалено %d старых элементов (>%d дней)", removed, max_age)


def _user_dl_dir(chat_id: int) -> str:
    d = os.path.join(DOWNLOADS_ROOT, str(chat_id))
    os.makedirs(d, exist_ok=True)
    return d


def _user_excel_path(chat_id: int) -> str:
    os.makedirs(REPORTS_ROOT, exist_ok=True)
    return os.path.join(REPORTS_ROOT, f"{chat_id}.xlsx")


async def run_search_pipeline(
    cfg: Config,
    bot: Bot,
    chat_id: int,
    status_msg: Message,
) -> Optional[Dict[str, Any]]:
    """
    1. Поиск тендеров (мульти-страницы)
    2. Скачивание ТЗ (shared browser)
    3. AI-анализ
    4. Excel
    """
    start_time = time.time()

    # ── ЭТАП 1 ────────────────────────────────────────────────
    await _update_status(status_msg,
        "▫️ Этап 1/4 — <b>Поиск на zakupki.gov.ru</b>...\n"
        "▪️ Этап 2/4 — Скачивание документов\n"
        "▪️ Этап 3/4 — AI-анализ ТЗ\n"
        "▪️ Этап 4/4 — Формирование отчёта"
    )

    tenders = await _parse_tenders(cfg, status_msg, chat_id)
    if not tenders:
        return None

    # ── ЭТАП 2 ────────────────────────────────────────────────
    await _update_status(status_msg,
        f"✅ Этап 1/4 — Найдено <b>{len(tenders)}</b> тендеров\n"
        f"▫️ Этап 2/4 — <b>Скачивание документов</b> (0/{len(tenders)})...\n"
        "▪️ Этап 3/4 — AI-анализ ТЗ\n"
        "▪️ Этап 4/4 — Формирование отчёта"
    )

    await _download_all_docs(tenders, status_msg, chat_id)

    # ── ЭТАП 3 ────────────────────────────────────────────────
    await _update_status(status_msg,
        f"✅ Этап 1/4 — Найдено <b>{len(tenders)}</b> тендеров\n"
        f"✅ Этап 2/4 — Документы скачаны\n"
        f"▫️ Этап 3/4 — <b>AI-анализ ТЗ</b>...\n"
        "▪️ Этап 4/4 — Формирование отчёта"
    )

    analyzed_count = 0
    results_data = []

    for idx, tender in enumerate(tenders, 1):
        analysis = await _analyze_tender(tender["id"], cfg, chat_id)
        if analysis:
            tender["analysis"] = analysis
            analyzed_count += 1
            results_data.append({
                "ID Тендера": tender["id"],
                "Название": tender.get("name", "—"),
                "Цена": tender.get("price", "—"),
                "Ссылка": str(tender.get("url", "")),
                "AI Анализ": analysis,
            })

        if idx % 2 == 0 or idx == len(tenders):
            await _update_status(status_msg,
                f"✅ Этап 1/4 — Найдено <b>{len(tenders)}</b> тендеров\n"
                f"✅ Этап 2/4 — Документы скачаны\n"
                f"▫️ Этап 3/4 — <b>AI-анализ</b> ({idx}/{len(tenders)})...\n"
                "▪️ Этап 4/4 — Формирование отчёта"
            )

    # ── ЭТАП 4 ────────────────────────────────────────────────
    await _update_status(status_msg,
        f"✅ Этап 1/4 — Найдено <b>{len(tenders)}</b> тендеров\n"
        f"✅ Этап 2/4 — Документы скачаны\n"
        f"✅ Этап 3/4 — Проанализировано <b>{analyzed_count}</b> ТЗ\n"
        f"▫️ Этап 4/4 — <b>Формирование отчёта</b>..."
    )

    excel_path = _build_excel(results_data, chat_id) if results_data else None

    elapsed = time.time() - start_time
    elapsed_str = f"{int(elapsed // 60)} мин {int(elapsed % 60)} сек"

    await _update_status(status_msg,
        f"✅ Этап 1/4 — Найдено <b>{len(tenders)}</b> тендеров\n"
        f"✅ Этап 2/4 — Документы скачаны\n"
        f"✅ Этап 3/4 — Проанализировано <b>{analyzed_count}</b> ТЗ\n"
        f"✅ Этап 4/4 — Отчёт готов\n\n"
        f"⏱ <b>{elapsed_str}</b>"
    )

    return {
        "tenders": tenders,
        "analyzed": analyzed_count,
        "excel_path": excel_path,
        "elapsed": elapsed_str,
    }


# ══════════════════════════════════════════════════════════════
#  Обёртки над существующими модулями
# ══════════════════════════════════════════════════════════════

async def _parse_tenders(cfg: Config, status_msg: Message, chat_id: int) -> list:
    """Мульти-страничный поиск с дедупликацией."""
    from playwright.async_api import async_playwright
    from browser_ctx import PLAYWRIGHT_CONTEXT_KWARGS, playwright_headless
    from parser import fetch_and_parse_page

    max_pages = max(1, min(cfg.max_pages, 10))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=playwright_headless())
        context = await browser.new_context(**PLAYWRIGHT_CONTEXT_KWARGS)
        page = await context.new_page()

        try:
            all_tenders: list[dict] = []
            seen_ids: set[str] = set()

            for pnum in range(1, max_pages + 1):
                url = cfg.build_search_url(page=pnum)
                log.info("Парсинг стр. %d/%d: %s", pnum, max_pages, url)

                if max_pages > 1:
                    await _update_status(status_msg,
                        f"▫️ Этап 1/4 — <b>Поиск</b> (стр. {pnum}/{max_pages}, "
                        f"найдено {len(all_tenders)})...\n"
                        "▪️ Этап 2/4 — Скачивание документов\n"
                        "▪️ Этап 3/4 — AI-анализ ТЗ\n"
                        "▪️ Этап 4/4 — Формирование отчёта"
                    )

                try:
                    items = await fetch_and_parse_page(page, url)
                except Exception:
                    if pnum == 1:
                        raise
                    log.info("Стр. %d — нет карточек, конец выдачи", pnum)
                    break

                if not items:
                    break

                for t in items:
                    if t.tender_id in seen_ids:
                        continue
                    seen_ids.add(t.tender_id)
                    all_tenders.append({
                        "id": t.tender_id,
                        "price": t.price,
                        "name": t.name,
                        "url": str(t.url),
                        "pub_date": t.pub_date,
                        "org_name": t.org_name,
                    })

                if pnum < max_pages:
                    await asyncio.sleep(1.5)

            log.info("Найдено тендеров: %d", len(all_tenders))
            return all_tenders

        except Exception:
            log.exception("Ошибка парсинга")
            try:
                await page.screenshot(
                    path=os.path.join(_user_dl_dir(chat_id), "error_screenshot.png")
                )
            except Exception:
                pass
            if all_tenders:
                log.info(
                    "Возвращаем %d частично собранных тендеров",
                    len(all_tenders),
                )
                return all_tenders
            raise
        finally:
            await browser.close()


async def _download_all_docs(
    tenders: list, status_msg: Message, chat_id: int,
) -> None:
    """Скачивание документов через один общий браузер."""
    from downloader import get_tender_docs, shared_download_browser

    total = len(tenders)
    dl_dir = _user_dl_dir(chat_id)

    async with shared_download_browser() as page:
        for i, tender in enumerate(tenders, 1):
            try:
                await get_tender_docs(
                    page, str(tender["url"]), tender["id"],
                    base_dir=dl_dir,
                )
            except Exception as e:
                log.warning("Ошибка скачивания %s: %s", tender["id"], e)

            if i % 2 == 0 or i == total:
                await _update_status(status_msg,
                    f"✅ Этап 1/4 — Найдено <b>{total}</b> тендеров\n"
                    f"▫️ Этап 2/4 — <b>Скачивание</b> ({i}/{total})...\n"
                    "▪️ Этап 3/4 — AI-анализ ТЗ\n"
                    "▪️ Этап 4/4 — Формирование отчёта"
                )

            if i < total:
                await asyncio.sleep(3)


async def _analyze_tender(
    tender_id: str, cfg: Config, chat_id: int,
) -> Optional[str]:
    tender_path = os.path.join(_user_dl_dir(chat_id), tender_id)
    if not os.path.isdir(tender_path):
        return None

    try:
        from reader import extract_text_from_file
        from tz_docs import is_tz_file
        from llm import call_ollama
    except ImportError:
        return None

    for filename in os.listdir(tender_path):
        if is_tz_file(filename):
            file_path = os.path.join(tender_path, filename)
            text = extract_text_from_file(file_path)
            if len(text) > 500:
                try:
                    return await asyncio.to_thread(
                        call_ollama, text, tender_id, cfg.ollama_model
                    )
                except Exception as e:
                    log.warning("LLM-ошибка для %s: %s", tender_id, e)
                    return None
    return None


def _build_excel(results_data: list, chat_id: int) -> str:
    import pandas as pd
    df = pd.DataFrame(results_data)
    path = _user_excel_path(chat_id)
    df.to_excel(path, index=False, engine="openpyxl")
    return path


async def _update_status(msg: Message, progress_text: str):
    try:
        await msg.edit_text(f"⏳ <b>Выполняется поиск...</b>\n\n{progress_text}")
    except Exception:
        pass

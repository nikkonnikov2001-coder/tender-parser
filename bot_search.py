"""
Поисковый конвейер с прогрессом в Telegram.
Интегрируется с parser/downloader/analyzer,
обновляет статус-сообщение на каждом этапе.
"""

import asyncio
import os
import time
import logging
from typing import Dict, Any, Optional

from aiogram import Bot
from aiogram.types import Message

from bot_config import Config

log = logging.getLogger("tender_bot.search")


async def run_search_pipeline(
    cfg: Config,
    bot: Bot,
    chat_id: int,
    status_msg: Message,
) -> Optional[Dict[str, Any]]:
    """
    1. Поиск тендеров  2. Скачивание ТЗ  3. AI-анализ  4. Excel
    """
    start_time = time.time()

    # ── ЭТАП 1 ────────────────────────────────────────────────
    await _update_status(status_msg,
        "▫️ Этап 1/4 — <b>Поиск на zakupki.gov.ru</b>...\n"
        "▪️ Этап 2/4 — Скачивание документов\n"
        "▪️ Этап 3/4 — AI-анализ ТЗ\n"
        "▪️ Этап 4/4 — Формирование отчёта"
    )

    tenders = await _parse_tenders(cfg)
    if not tenders:
        return None

    # ── ЭТАП 2 ────────────────────────────────────────────────
    await _update_status(status_msg,
        f"✅ Этап 1/4 — Найдено <b>{len(tenders)}</b> тендеров\n"
        f"▫️ Этап 2/4 — <b>Скачивание документов</b> (0/{len(tenders)})...\n"
        "▪️ Этап 3/4 — AI-анализ ТЗ\n"
        "▪️ Этап 4/4 — Формирование отчёта"
    )

    for i, tender in enumerate(tenders, 1):
        try:
            await _download_tender_docs(str(tender["url"]), tender["id"])
        except Exception as e:
            log.warning("Ошибка скачивания %s: %s", tender["id"], e)

        if i % 2 == 0 or i == len(tenders):
            await _update_status(status_msg,
                f"✅ Этап 1/4 — Найдено <b>{len(tenders)}</b> тендеров\n"
                f"▫️ Этап 2/4 — <b>Скачивание</b> ({i}/{len(tenders)})...\n"
                "▪️ Этап 3/4 — AI-анализ ТЗ\n"
                "▪️ Этап 4/4 — Формирование отчёта"
            )

        if i < len(tenders):
            await asyncio.sleep(3)

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
        analysis = await _analyze_tender(tender["id"], cfg)
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

    excel_path = _build_excel(results_data) if results_data else None

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

async def _parse_tenders(cfg: Config) -> list:
    from playwright.async_api import async_playwright
    from bs4 import BeautifulSoup
    from browser_ctx import PLAYWRIGHT_CONTEXT_KWARGS

    url = cfg.build_search_url()
    log.info("Парсинг: %s", url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(**PLAYWRIGHT_CONTEXT_KWARGS)
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2000)
            await page.keyboard.press("Escape")
            await page.wait_for_selector(
                "div.search-registry-entry-block", timeout=30000
            )

            html = await page.content()
            soup = BeautifulSoup(html, "lxml")
            blocks = soup.find_all("div", class_="search-registry-entry-block")

            tenders = []
            for block in blocks:
                id_tag = block.find("div", class_="registry-entry__header-mid__number")
                tender_id = id_tag.text.strip().replace("№ ", "") if id_tag else None
                if not tender_id:
                    continue

                link_tag = id_tag.find("a") if id_tag else None
                href = (
                    "https://zakupki.gov.ru" + link_tag["href"]
                    if link_tag and "href" in link_tag.attrs else ""
                )

                price_tag = block.find("div", class_="price-block__value")
                price = price_tag.text.strip().replace("\xa0", " ") if price_tag else "—"

                name_tag = block.find("div", class_="registry-entry__body-value")
                name = name_tag.text.strip() if name_tag else "—"

                # Дата публикации
                date_tag = block.find("div", class_="data-block__value")
                pub_date = date_tag.text.strip() if date_tag else "—"

                # Заказчик
                org_tag = block.find("div", class_="registry-entry__body-href")
                org_name = org_tag.text.strip() if org_tag else "—"

                tenders.append({
                    "id": tender_id,
                    "price": price,
                    "name": name,
                    "url": href,
                    "pub_date": pub_date,
                    "org_name": org_name,
                })

            log.info("Найдено тендеров: %d", len(tenders))
            return tenders

        except Exception:
            log.exception("Ошибка парсинга")
            await page.screenshot(path="error_screenshot.png")
            raise
        finally:
            await browser.close()


async def _download_tender_docs(tender_url: str, tender_id: str):
    try:
        from downloader import get_tender_docs
        await get_tender_docs(tender_url, tender_id)
    except ImportError:
        log.warning("downloader.py не найден — пропускаем скачивание")
    except Exception as e:
        log.warning("Ошибка скачивания %s: %s", tender_id, e)


async def _analyze_tender(tender_id: str, cfg: Config) -> Optional[str]:
    tender_path = os.path.join("downloads", tender_id)
    if not os.path.isdir(tender_path):
        return None

    try:
        from reader import extract_text_from_docx
        from tz_docs import is_tz_docx
    except ImportError:
        return None

    for filename in os.listdir(tender_path):
        if is_tz_docx(filename):
            file_path = os.path.join(tender_path, filename)
            text = extract_text_from_docx(file_path)
            if len(text) > 500:
                return await asyncio.to_thread(
                    _call_ollama, text, tender_id, cfg.ollama_model
                )
    return None


def _call_ollama(text: str, tender_id: str, model: str) -> str:
    import requests

    ollama_url = os.environ.get(
        "OLLAMA_URL", "http://localhost:11434/api/generate"
    ).strip()
    timeout = int(os.environ.get("OLLAMA_TIMEOUT_SEC", "600"))
    safe_text = text[:25000]

    prompt = (
        "Ты — профессиональный тендерный аналитик. "
        "Прочитай выдержку из Технического задания и составь краткую выжимку.\n\n"
        "Структура ответа:\n"
        "1. Предмет контракта\n"
        "2. Сроки\n"
        "3. Требования и штрафы\n\n"
        f"Текст ТЗ:\n{safe_text}"
    )

    try:
        resp = requests.post(ollama_url, json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 16384},
        }, timeout=timeout)
        if resp.status_code == 200:
            return resp.json().get("response", "")
        return f"Ошибка API: {resp.status_code}"
    except Exception as e:
        return f"Ошибка Ollama: {e}"


def _build_excel(results_data: list) -> str:
    import pandas as pd
    df = pd.DataFrame(results_data)
    path = "Tenders_Analytics_DB.xlsx"
    df.to_excel(path, index=False, engine="openpyxl")
    return path


async def _update_status(msg: Message, progress_text: str):
    try:
        await msg.edit_text(f"⏳ <b>Выполняется поиск...</b>\n\n{progress_text}")
    except Exception:
        pass

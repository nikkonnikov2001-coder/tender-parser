import asyncio
import logging
import os
import sys

import load_env  # noqa: F401 — загрузка .env до этапов с notifier/analyzer
from analyzer import EXCEL_FILENAME, run_analytics
from downloader import get_tender_docs, shared_download_browser
from notifier import send_telegram_report
from parser import parse_tenders_heavy
from tenders_manifest import DEFAULT_MANIFEST_PATH, write_tenders_manifest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tender_bot.main")

def _download_delay_sec() -> float:
    raw = os.environ.get("DOWNLOAD_DELAY_SEC", "5").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 5.0


def _max_tenders_cap():
    raw = os.environ.get("PIPELINE_MAX_TENDERS", "").strip()
    if not raw:
        return None
    try:
        n = int(raw)
        return n if n > 0 else None
    except ValueError:
        return None


def _skip_existing_downloads() -> bool:
    return os.environ.get("SKIP_EXISTING_DOWNLOADS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _print_cli_help() -> None:
    print(
        """Парсер тендеров ЕИС → скачивание документов → Ollama → Excel → Telegram.

  python main.py              полный конвейер
  python main.py analyze-only только анализ downloads/ + манифест и отправка Excel
  python main.py download-only поиск и скачивание (без LLM и Telegram)

Переменные см. .env.example (EIS_*, DOWNLOAD_DELAY_SEC, PIPELINE_MAX_TENDERS,
SKIP_EXISTING_AI_ANALYSIS, …)."""
    )


def _download_dir_has_files(tender_id: str) -> bool:
    base = os.path.join("downloads", tender_id)
    if not os.path.isdir(base):
        return False
    with os.scandir(base) as it:
        return any(entry.is_file() for entry in it)


async def _search_and_prepare_tenders():
    log.info("[ЭТАП 1/4] Поиск свежих тендеров...")
    tenders = await parse_tenders_heavy()
    cap = _max_tenders_cap()
    if cap is not None and len(tenders) > cap:
        log.info("PIPELINE_MAX_TENDERS=%d: обрабатываем первые %d из %d.", cap, cap, len(tenders))
        tenders = tenders[:cap]

    if not tenders:
        return []

    write_tenders_manifest(tenders, DEFAULT_MANIFEST_PATH)
    return tenders


async def _download_tenders_batch(tenders, *, stage_label: str = "[ЭТАП 2/4]") -> None:
    skip_existing = _skip_existing_downloads()
    if skip_existing:
        log.info("SKIP_EXISTING_DOWNLOADS: пропускаем папки, где уже есть файлы.")

    needs_browser = any(
        not (skip_existing and _download_dir_has_files(t.tender_id)) for t in tenders
    )

    log.info("%s Скачивание документов для %d тендеров...", stage_label, len(tenders))
    if needs_browser:
        log.info("Один сеанс Playwright (Chromium) на всё скачивание.")

    if needs_browser:
        async with shared_download_browser() as page:
            for index, tender in enumerate(tenders, start=1):
                log.info("Обработка %d/%d (ID: %s)", index, len(tenders), tender.tender_id)
                if skip_existing and _download_dir_has_files(tender.tender_id):
                    log.info("Уже есть скачанные файлы — пропуск.")
                    continue
                await get_tender_docs(page, str(tender.url), tender.tender_id)
                delay = _download_delay_sec()
                if index < len(tenders) and delay > 0:
                    await asyncio.sleep(delay)
    else:
        for index, tender in enumerate(tenders, start=1):
            log.info("Обработка %d/%d (ID: %s)", index, len(tenders), tender.tender_id)
            if skip_existing and _download_dir_has_files(tender.tender_id):
                log.info("Уже есть скачанные файлы — пропуск.")


async def run_pipeline():
    log.info("=== ЗАПУСК ПОЛНОГО AI-КОНВЕЙЕРА ТЕНДЕРОВ ===")

    tenders = await _search_and_prepare_tenders()
    if not tenders:
        log.warning("Тендеры не найдены или произошла ошибка. Завершаем работу.")
        return

    await _download_tenders_batch(tenders)

    log.info("[ЭТАП 3/4] Чтение ТЗ и анализ нейросетью...")
    run_analytics(manifest_path=DEFAULT_MANIFEST_PATH)

    log.info("[ЭТАП 4/4] Отправка результатов ботом...")

    if os.path.exists(EXCEL_FILENAME):
        send_telegram_report(EXCEL_FILENAME)
    else:
        log.error("Excel файл не найден, отправлять нечего.")

    log.info("=== КОНВЕЙЕР УСПЕШНО ОТРАБОТАЛ! ===")

def _is_analyze_only(argv: list[str]) -> bool:
    for a in argv[1:]:
        if a.strip().lower() in ("analyze-only", "analyze_only", "--analyze-only"):
            return True
    return False


def _is_download_only(argv: list[str]) -> bool:
    for a in argv[1:]:
        if a.strip().lower() in ("download-only", "download_only", "--download-only"):
            return True
    return False


def _is_help(argv: list[str]) -> bool:
    if len(argv) <= 1:
        return False
    return argv[1].strip().lower() in ("-h", "--help", "help")


def run_analyze_only():
    """Только анализ и Telegram: папка downloads/ и опционально tenders_manifest.json."""
    log.info("=== РЕЖИМ: только анализ (без поиска и скачивания) ===")
    log.info("[ЭТАП 3/4] Анализ уже скачанных ТЗ...")
    run_analytics(manifest_path=DEFAULT_MANIFEST_PATH)

    log.info("[ЭТАП 4/4] Отправка в Telegram...")
    if os.path.exists(EXCEL_FILENAME):
        send_telegram_report(EXCEL_FILENAME)
    else:
        log.error("Excel не создан — нечего отправлять.")

    log.info("=== ГОТОВО ===")


async def run_download_only():
    """Поиск и скачивание без Ollama и Telegram."""
    log.info("=== РЕЖИМ: только поиск и скачивание (без анализа) ===")
    tenders = await _search_and_prepare_tenders()
    if not tenders:
        log.warning("Тендеры не найдены или произошла ошибка. Завершаем работу.")
        return
    await _download_tenders_batch(tenders, stage_label="[СКАЧИВАНИЕ]")
    log.info("=== Скачивание завершено (анализ: python main.py analyze-only) ===")


if __name__ == "__main__":
    if _is_help(sys.argv):
        _print_cli_help()
    elif _is_analyze_only(sys.argv):
        run_analyze_only()
    elif _is_download_only(sys.argv):
        asyncio.run(run_download_only())
    else:
        asyncio.run(run_pipeline())
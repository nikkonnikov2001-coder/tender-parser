import logging
import os
from pathlib import Path

import load_env  # noqa: F401
import pandas as pd

from llm import call_ollama, OllamaError
from reader import extract_text_from_file
from tenders_manifest import load_tenders_manifest
from tz_docs import is_tz_file

log = logging.getLogger("tender_bot.analyzer")

EXCEL_COLUMNS = [
    "ID Тендера",
    "Ссылка ЕИС",
    "Название (поиск)",
    "Цена (поиск)",
    "Имя файла ТЗ",
    "AI Анализ (Предмет, Сроки, Штрафы)",
]

EXCEL_FILENAME = "Tenders_Analytics_DB.xlsx"


def _excel_merge_existing() -> bool:
    return os.environ.get("EXCEL_MERGE_EXISTING", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _skip_existing_ai_analysis() -> bool:
    return os.environ.get("SKIP_EXISTING_AI_ANALYSIS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _analysis_min_text_chars() -> int:
    try:
        n = int(os.environ.get("ANALYSIS_MIN_TEXT_CHARS", "500"))
    except ValueError:
        n = 500
    return max(50, min(n, 200_000))


def _load_tz_plaintext(file_path: str, filename: str) -> str:
    try:
        return extract_text_from_file(file_path)
    except Exception as e:
        log.warning("Ошибка чтения %s: %s", filename, e)
    return ""


def _normalize_excel_df(df: pd.DataFrame) -> pd.DataFrame:
    for col in EXCEL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[EXCEL_COLUMNS]


def _save_excel_with_optional_merge(df_new: pd.DataFrame) -> None:
    path = EXCEL_FILENAME
    if _excel_merge_existing() and os.path.isfile(path):
        try:
            df_old = pd.read_excel(path)
            df_old = _normalize_excel_df(df_old)
            df_new = _normalize_excel_df(df_new.copy())
            merged = pd.concat([df_old, df_new], ignore_index=True)
            merged = merged.drop_duplicates(
                subset=["ID Тендера", "Имя файла ТЗ"],
                keep="last",
            )
            log.info("EXCEL_MERGE_EXISTING: объединено (%d строк).", len(merged))
            merged.to_excel(path, index=False)
            return
        except Exception as e:
            log.warning("Не удалось слить старый Excel (%s), перезаписываем.", e)
    df_new = _normalize_excel_df(df_new.copy())
    df_new.to_excel(path, index=False)


def run_analytics(base_dir="downloads", manifest_path: str | Path | None = None):
    log.info("=== СТАРТ AI-АНАЛИТИКИ (С ЭКСПОРТОМ В EXCEL) ===")

    manifest: dict[str, dict[str, str]] = {}
    if manifest_path is not None:
        manifest = load_tenders_manifest(manifest_path)
        if manifest:
            log.info("Подмешиваем метаданные из манифеста (%d id).", len(manifest))

    results_data = []
    min_chars = _analysis_min_text_chars()

    for tender_id in os.listdir(base_dir):
        tender_path = os.path.join(base_dir, tender_id)
        if not os.path.isdir(tender_path):
            continue

        for file in sorted(os.listdir(tender_path)):
            if not is_tz_file(file):
                continue
            file_path = os.path.join(tender_path, file)
            text = _load_tz_plaintext(file_path, file)

            if len(text) <= min_chars:
                if text.strip():
                    log.info(
                        "%s: мало текста (%d симв., порог %d) — пропуск LLM.",
                        file, len(text), min_chars,
                    )
                continue

            log.info("Документ: %s", file)

            report_path = os.path.join(tender_path, "AI_Анализ.txt")
            if _skip_existing_ai_analysis() and os.path.isfile(report_path):
                with open(report_path, encoding="utf-8") as f:
                    analysis = f.read()
                log.info("SKIP_EXISTING_AI_ANALYSIS: %s (%d симв.)", report_path, len(analysis))
            else:
                log.info("LLM анализирует тендер %s (%d симв.)...", tender_id, len(text))
                try:
                    analysis = call_ollama(text, tender_id)
                except OllamaError as e:
                    log.warning("LLM-ошибка для %s: %s", tender_id, e)
                    continue
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(analysis)

            log.info("Резюме:\n%s", analysis)

            meta = manifest.get(tender_id, {})
            results_data.append(
                {
                    "ID Тендера": tender_id,
                    "Ссылка ЕИС": meta.get("url", ""),
                    "Название (поиск)": meta.get("search_title", ""),
                    "Цена (поиск)": meta.get("search_price", ""),
                    "Имя файла ТЗ": file,
                    "AI Анализ (Предмет, Сроки, Штрафы)": analysis,
                }
            )

    if results_data:
        log.info("Формируем Excel-базу данных...")
        df = pd.DataFrame(results_data)
        _save_excel_with_optional_merge(df)
        log.info("Готово! Таблица: %s", EXCEL_FILENAME)
    else:
        log.warning("Нечего сохранять в таблицу. Тендеры не проанализированы.")

if __name__ == "__main__":
    run_analytics()
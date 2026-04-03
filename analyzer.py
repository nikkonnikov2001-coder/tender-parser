import os
from pathlib import Path

import load_env  # noqa: F401
import pandas as pd
import requests

from reader import extract_text_from_docx, extract_text_from_pdf
from tenders_manifest import load_tenders_manifest
from tz_docs import is_tz_docx, is_tz_pdf

OLLAMA_URL = os.environ.get(
    "OLLAMA_URL", "http://localhost:11434/api/generate"
).strip()
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b").strip()

try:
    OLLAMA_TIMEOUT_SEC = int(os.environ.get("OLLAMA_TIMEOUT_SEC", "600"))
except ValueError:
    OLLAMA_TIMEOUT_SEC = 600

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
    low = filename.lower()
    try:
        if low.endswith(".docx"):
            return extract_text_from_docx(file_path)
        if low.endswith(".pdf"):
            return extract_text_from_pdf(file_path)
    except Exception as e:
        print(f"⚠️ Ошибка чтения {filename}: {e}")
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
            print(
                f"📎 EXCEL_MERGE_EXISTING: объединено с предыдущим файлом "
                f"({len(merged)} строк)."
            )
            merged.to_excel(path, index=False)
            return
        except Exception as e:
            print(f"⚠️ Не удалось прочитать/слить старый Excel ({e}), перезаписываем.")
    df_new = _normalize_excel_df(df_new.copy())
    df_new.to_excel(path, index=False)


def analyze_tender_with_llm(text, tender_id):
    safe_text = text[:25000] 
    print(f"🧠 Нейросеть читает тендер {tender_id} (Текст: {len(safe_text)} симв.)...")
    
    prompt = f"""
Ты — профессиональный тендерный аналитик. Прочитай выдержку из Технического задания (ТЗ) и составь выжимку без воды.

Структура ответа:
1. Предмет контракта: (Что нужно сделать)
2. Сроки: (Даты)
3. Требования и штрафы: (Важные условия)

Текст ТЗ:
{safe_text}
"""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 16384 
        }
    }

    try:
        response = requests.post(
            OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT_SEC
        )
        if response.status_code == 200:
            return response.json().get("response", "")
        return f"❌ Ошибка API: {response.status_code}"
    except Exception as e:
        return f"❌ Ошибка Ollama: {e}"

def run_analytics(base_dir="downloads", manifest_path: str | Path | None = None):
    print("=== 🤖 СТАРТ AI-АНАЛИТИКИ (С ЭКСПОРТОМ В EXCEL) ===\n")

    manifest: dict[str, dict[str, str]] = {}
    if manifest_path is not None:
        manifest = load_tenders_manifest(manifest_path)
        if manifest:
            print(f"📎 Подмешиваем метаданные из манифеста ({len(manifest)} id).\n")

    results_data = []
    min_chars = _analysis_min_text_chars()

    for tender_id in os.listdir(base_dir):
        tender_path = os.path.join(base_dir, tender_id)
        if not os.path.isdir(tender_path):
            continue

        for file in sorted(os.listdir(tender_path)):
            if not (is_tz_docx(file) or is_tz_pdf(file)):
                continue
            file_path = os.path.join(tender_path, file)
            text = _load_tz_plaintext(file_path, file)

            if len(text) <= min_chars:
                if text.strip():
                    print(
                        f"   ⚠️ {file}: извлечено мало текста ({len(text)} симв., "
                        f"порог ANALYSIS_MIN_TEXT_CHARS={min_chars}) — пропуск LLM."
                    )
                continue

            print(f"\n" + "="*60)
            print(f"📄 Документ: {file}")

            report_path = os.path.join(tender_path, "AI_Анализ.txt")
            if _skip_existing_ai_analysis() and os.path.isfile(report_path):
                with open(report_path, encoding="utf-8") as f:
                    analysis = f.read()
                print(
                    "⏭️ SKIP_EXISTING_AI_ANALYSIS: используем сохранённый "
                    f"{report_path} ({len(analysis)} симв.)"
                )
            else:
                analysis = analyze_tender_with_llm(text, tender_id)
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(analysis)

            print("\n📋 РЕЗЮМЕ:")
            print(analysis)
            print("="*60 + "\n")

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
        print("📊 Формируем Excel-базу данных...")
        df = pd.DataFrame(results_data)
        _save_excel_with_optional_merge(df)
        print(f"✅ Готово! Таблица: {EXCEL_FILENAME}")
    else:
        print("⚠️ Нечего сохранять в таблицу. Тендеры не проанализированы.")

if __name__ == "__main__":
    run_analytics()
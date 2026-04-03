import os

import load_env  # noqa: F401
import pandas as pd
import requests

from reader import extract_text_from_docx
from tz_docs import is_tz_docx

OLLAMA_URL = os.environ.get(
    "OLLAMA_URL", "http://localhost:11434/api/generate"
).strip()
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b").strip()
OLLAMA_TIMEOUT_SEC = int(os.environ.get("OLLAMA_TIMEOUT_SEC", "600"))

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

def run_analytics(base_dir="downloads"):
    print("=== 🤖 СТАРТ AI-АНАЛИТИКИ (С ЭКСПОРТОМ В EXCEL) ===\n")
    
    # Сюда мы будем складывать результаты по каждому тендеру
    results_data = [] 
    
    for tender_id in os.listdir(base_dir):
        tender_path = os.path.join(base_dir, tender_id)
        if not os.path.isdir(tender_path):
            continue
            
        for file in os.listdir(tender_path):
            if is_tz_docx(file):
                file_path = os.path.join(tender_path, file)
                text = extract_text_from_docx(file_path)
                
                if len(text) > 500:
                    print(f"\n" + "="*60)
                    print(f"📄 Документ: {file}")
                    
                    analysis = analyze_tender_with_llm(text, tender_id)
                    
                    print("\n📋 РЕЗЮМЕ:")
                    print(analysis)
                    print("="*60 + "\n")
                    
                    # Сохраняем текстовый файл в папку (как было)
                    report_path = os.path.join(tender_path, "AI_Анализ.txt")
                    with open(report_path, "w", encoding="utf-8") as f:
                        f.write(analysis)
                        
                    # ДОБАВЛЕНО: Упаковываем данные в словарь для Excel
                    results_data.append({
                        "ID Тендера": tender_id,
                        "Имя файла ТЗ": file,
                        "AI Анализ (Предмет, Сроки, Штрафы)": analysis
                    })

    # ДОБАВЛЕНО: Финальная выгрузка в таблицу
    if results_data:
        print("📊 Формируем Excel-базу данных...")
        # Превращаем наш список словарей в датафрейм (таблицу)
        df = pd.DataFrame(results_data)
        excel_filename = "Tenders_Analytics_DB.xlsx"
        
        # Сохраняем на диск
        df.to_excel(excel_filename, index=False)
        print(f"✅ Готово! Таблица сохранена в корень проекта: {excel_filename}")
    else:
        print("⚠️ Нечего сохранять в таблицу. Тендеры не проанализированы.")

if __name__ == "__main__":
    run_analytics()
import os
import requests
from reader import extract_text_from_docx

# Настройки под ноутбук (8 ГБ VRAM)
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b" # Легкая квантованная версия

def analyze_tender_with_llm(text, tender_id):
    print(f"🧠 Нейросеть читает тендер {tender_id} (Текст: {len(text)} симв.)...")
    
    # Обрезаем текст до 60 000 символов, чтобы не вылететь за пределы 8 ГБ VRAM
    safe_text = text[:60000] 
    
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
            "num_ctx": 16384 # Расширяем память модели до 16к токенов
        }
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=300)
        if response.status_code == 200:
            return response.json().get("response", "")
        return f"❌ Ошибка API: {response.status_code}"
    except Exception as e:
        return f"❌ Ошибка Ollama: {e}"

def run_analytics(base_dir="downloads"):
    print("=== 🤖 СТАРТ AI-АНАЛИТИКИ НА RTX 3070 ===\n")
    
    for tender_id in os.listdir(base_dir):
        tender_path = os.path.join(base_dir, tender_id)
        if not os.path.isdir(tender_path):
            continue
            
        for file in os.listdir(tender_path):
            if ("тз" in file.lower() or "техническое_задание" in file.lower() or "описание_объекта" in file.lower() or "контракт" in file.lower()) and file.endswith(".docx"):
                file_path = os.path.join(tender_path, file)
                text = extract_text_from_docx(file_path)
                
                if len(text) > 500:
                    print(f"\n" + "="*60)
                    print(f"📄 Документ: {file}")
                    
                    analysis = analyze_tender_with_llm(text, tender_id)
                    
                    print("\n📋 РЕЗЮМЕ:")
                    print(analysis)
                    print("="*60 + "\n")
                    
                    report_path = os.path.join(tender_path, "AI_Анализ.txt")
                    with open(report_path, "w", encoding="utf-8") as f:
                        f.write(analysis)

if __name__ == "__main__":
    run_analytics()
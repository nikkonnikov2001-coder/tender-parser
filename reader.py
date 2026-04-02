import os
from docx import Document

def extract_text_from_docx(file_path):
    doc = Document(file_path)
    text_content = []
    
    # 1. Читаем обычные абзацы
    for para in doc.paragraphs:
        if para.text.strip():
            text_content.append(para.text.strip())
            
    # 2. КРИТИЧЕСКИ ВАЖНО: Читаем таблицы (тут прячется всё ТЗ)
    for table in doc.tables:
        for row in table.rows:
            row_data = []
            for cell in row.cells:
                clean_text = cell.text.strip().replace('\n', ' ')
                # Добавляем текст ячейки, если он не пустой и мы его еще не добавили
                # (в docx бывают объединенные ячейки, которые дублируют текст)
                if clean_text and clean_text not in row_data:
                    row_data.append(clean_text)
            if row_data:
                # Склеиваем строку таблицы через разделитель
                text_content.append(" | ".join(row_data))
                
    return "\n".join(text_content)

def get_tz_text(base_dir="downloads"):
    print("🔍 Начинаем глубокий поиск и чтение ТЗ...\n")
    
    for tender_id in os.listdir(base_dir):
        tender_path = os.path.join(base_dir, tender_id)
        
        if not os.path.isdir(tender_path):
            continue
            
        print(f"📁 Тендер: {tender_id}")
        tz_found = False
        
        for file in os.listdir(tender_path):
            lower_name = file.lower()
            # Ищем любые упоминания ТЗ, контракта или объекта закупки
            if ("тз" in lower_name or "техническое_задание" in lower_name or "описание_объекта" in lower_name or "контракт" in lower_name) and file.endswith(".docx"):
                file_path = os.path.join(tender_path, file)
                print(f"   📄 Читаем файл: {file}")
                
                try:
                    full_text = extract_text_from_docx(file_path)
                    
                    print(f"   ✅ Текст вытащен! Длина: {len(full_text)} символов.")
                    print(f"   📝 Превью:\n   {full_text[:300]}...\n")
                    tz_found = True
                    
                except Exception as e:
                    print(f"   ❌ Ошибка чтения: {e}\n")
                    
        if not tz_found:
            print("   ⚠️ Нет подходящего .docx (скорее всего файлы в старом .doc, .rtf или .pdf)\n")

if __name__ == "__main__":
    get_tz_text()
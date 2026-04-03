import asyncio
import os

import load_env  # noqa: F401 — загрузка .env до этапов с notifier/analyzer
from parser import parse_tenders_heavy
from downloader import get_tender_docs
from analyzer import run_analytics
from notifier import send_telegram_report

async def run_pipeline():
    print("=== 🔥 ЗАПУСК ПОЛНОГО AI-КОНВЕЙЕРА ТЕНДЕРОВ 🔥 ===")
    
    # ЭТАП 1: ПОИСК (Работает parser.py)
    print("\n[ЭТАП 1/4] Поиск свежих тендеров...")
    tenders = await parse_tenders_heavy()
    
    if not tenders:
        print("Тендеры не найдены или произошла ошибка. Завершаем работу.")
        return

    # ЭТАП 2: СКАЧИВАНИЕ (Работает downloader.py)
    print(f"\n[ЭТАП 2/4] Скачивание документов для {len(tenders)} тендеров...")
    for index, tender in enumerate(tenders, start=1):
        print(f"\n⏳ Обработка {index} из {len(tenders)} (ID: {tender.tender_id})")
        await get_tender_docs(str(tender.url), tender.tender_id)
        
        # Антибан-пауза, чтобы ЕИС нас не заблокировала
        if index < len(tenders):
            await asyncio.sleep(5)

    # ЭТАП 3: АНАЛИТИКА И EXCEL (Работает analyzer.py)
    print("\n[ЭТАП 3/4] Чтение ТЗ и анализ нейросетью...")
    # Нейросеть прочтет скачанное и сама создаст Tenders_Analytics_DB.xlsx
    run_analytics()

    # ЭТАП 4: ОТПРАВКА В TELEGRAM (Работает notifier.py)
    print("\n[ЭТАП 4/4] Отправка результатов ботом...")
    excel_file = "Tenders_Analytics_DB.xlsx"
    
    if os.path.exists(excel_file):
        send_telegram_report(excel_file)
    else:
        print("❌ Excel файл не найден, отправлять нечего.")

    print("\n=== 🏁 КОНВЕЙЕР УСПЕШНО ОТРАБОТАЛ! 🏁 ===")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
import asyncio
from parser import parse_tenders_heavy
from downloader import get_tender_docs

async def main():
    print("=== 🟢 СТАРТ ПАЙПЛАЙНА ТЕНДЕРОВ ===")
    
    # 1. Запускаем поиск тендеров (наш фильтр: 5-30 млн, СФО и ПФО)
    tenders = await parse_tenders_heavy()
    
    if not tenders:
        print("Тендеры не найдены или произошла ошибка.")
        return

    print(f"\n=== 📥 НАЧИНАЕМ СКАЧИВАНИЕ ДОКУМЕНТОВ ({len(tenders)} тендеров) ===")
    
    # 2. Идем по списку и скачиваем документы для каждого
    for index, tender in enumerate(tenders, start=1):
        print(f"\n[{index}/{len(tenders)}] Обработка тендера: {tender.tender_id} (Сумма: {tender.price})")
        
        # Запускаем наш загрузчик
        await get_tender_docs(str(tender.url), tender.tender_id)
        
        # КРИТИЧЕСКИ ВАЖНО: Делаем паузу между тендерами, чтобы ЕИС не забанила нас за DDoS
        if index < len(tenders):
            print("⏳ Спим 5 секунд перед следующим тендером (антибан)...")
            await asyncio.sleep(5)

    print("\n=== 🏁 ПАЙПЛАЙН УСПЕШНО ЗАВЕРШЕН ===")

if __name__ == "__main__":
    asyncio.run(main())
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from pydantic import BaseModel, HttpUrl

from browser_ctx import PLAYWRIGHT_CONTEXT_KWARGS

class TenderItem(BaseModel):
    tender_id: str
    price: str
    name: str
    url: HttpUrl

async def parse_tenders_heavy():
    print("🚀 Запускаем парсер: СФО + ПФО, 5-30 млн руб (Прямой обход формы)...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        context = await browser.new_context(**PLAYWRIGHT_CONTEXT_KWARGS)
        page = await context.new_page()

        # ИСПОЛЬЗУЕМ results.html вместо search.html
        # Вшили цену (priceFromGeneral=5000000) и округа (districts=5277331%2C5277327) прямо в запрос
        url = (
            "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?"
            "searchString=организация+мероприятий&morphology=on&search-filter=Дате+размещения"
            "&pageNumber=1&sortDirection=false&recordsPerPage=_10&showLotsInfoHidden=false"
            "&sortBy=UPDATE_DATE&fz44=on&fz223=on&af=on&currencyIdGeneral=-1"
            "&priceFromGeneral=5000000&priceToGeneral=30000000"
            "&districts=5277331%2C5277327"
        )
        
        try:
            print("⏳ Идем напрямую на страницу результатов (без кликов по форме)...")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            await page.wait_for_timeout(2000)
            await page.keyboard.press('Escape')
            
            print("👀 Ждем отрисовки целевых тендеров...")
            await page.wait_for_selector('div.search-registry-entry-block', timeout=30000)
            
            html = await page.content()
            
            soup = BeautifulSoup(html, 'lxml')
            blocks = soup.find_all('div', class_='search-registry-entry-block')
            
            tenders_list = []
            
            for block in blocks:
                id_tag = block.find('div', class_='registry-entry__header-mid__number')
                tender_id = id_tag.text.strip().replace('№ ', '') if id_tag else "N/A"
                
                if tender_id == "N/A":
                    continue
                
                link_tag = id_tag.find('a') if id_tag else None
                href = "https://zakupki.gov.ru" + link_tag['href'] if link_tag and 'href' in link_tag.attrs else "https://zakupki.gov.ru"
                
                price_tag = block.find('div', class_='price-block__value')
                price = price_tag.text.strip().replace('\xa0', ' ') if price_tag else "N/A"
                
                name_tag = block.find('div', class_='registry-entry__body-value')
                name = name_tag.text.strip() if name_tag else "N/A"
                
                try:
                    tender = TenderItem(
                        tender_id=tender_id,
                        price=price,
                        name=name,
                        url=href
                    )
                    tenders_list.append(tender)
                except Exception as ve:
                    pass

            print(f"🎯 Найдено тендеров (Строго СФО и ПФО): {len(tenders_list)}\n")
            
            for t in tenders_list:
                print(f"📌 ID: {t.tender_id} | 💰 {t.price}")
            
            return tenders_list
                
        except Exception as e:
            print(f"\n❌ Ошибка загрузки: {e}")
            await page.screenshot(path="error_screenshot.png")
            return []
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(parse_tenders_heavy())
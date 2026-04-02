import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from pydantic import BaseModel, HttpUrl

class TenderItem(BaseModel):
    tender_id: str
    price: str
    name: str
    url: HttpUrl

async def parse_tenders_heavy():
    print("🚀 Запускаем парсер: СФО + ПФО, 5-30 млн руб...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            ignore_https_errors=True
        )
        page = await context.new_page()

        url = (
            "https://zakupki.gov.ru/epz/order/extendedsearch/search.html?"
            "searchString=организация+мероприятий&morphology=on&search-filter=Дате+размещения"
            "&pageNumber=1&sortDirection=false&recordsPerPage=_10&showLotsInfoHidden=false"
            "&sortBy=UPDATE_DATE&fz44=on&fz223=on&af=on&currencyIdGeneral=-1"
            "&districts=5277331%2C5277327"
        )
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            await page.wait_for_timeout(2000)
            await page.keyboard.press('Escape')
            await page.wait_for_timeout(1000)
            
            price_section = page.locator('text="Цена"').first
            await price_section.scroll_into_view_if_needed()
            await price_section.click()
            await page.wait_for_timeout(1000) 
            
            await page.locator('input[name="priceFromGeneral"]').fill('5000000')
            await page.locator('input[name="priceToGeneral"]').fill('30000000')
            await page.wait_for_timeout(500)
            
            apply_btn = page.locator('text="Применить"').first
            
            if await apply_btn.count() > 0:
                await apply_btn.scroll_into_view_if_needed()
                await apply_btn.click()
            else:
                search_input = page.locator('input[name="searchString"]').first
                box = await search_input.bounding_box()
                if box:
                    await page.mouse.click(box['x'] + box['width'] - 25, box['y'] + box['height'] / 2)

            await page.wait_for_timeout(3000) 
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

            print(f"🎯 Найдено и отвалидировано тендеров: {len(tenders_list)}\n")
            
            for t in tenders_list:
                print(f"📌 ID: {t.tender_id} | 💰 {t.price}")
            
            # Вот тот самый return, который отдаст список в main.py
            return tenders_list
                
        except Exception as e:
            print(f"\n❌ Ошибка загрузки: {e}")
            await page.screenshot(path="error_screenshot.png")
            return []
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(parse_tenders_heavy())
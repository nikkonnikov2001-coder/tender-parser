import asyncio
import os
from playwright.async_api import async_playwright
from curl_cffi import requests as curl_requests

from browser_ctx import PLAYWRIGHT_CONTEXT_KWARGS

async def get_tender_docs(url: str, tender_id: str):
    doc_url = url.replace("common-info.html", "documents.html")
    print(f"🚀 Летим в раздел документов: {doc_url}")
    
    # Создаем директорию для сохранения файлов
    save_dir = os.path.join("downloads", tender_id)
    os.makedirs(save_dir, exist_ok=True)
    print(f"📁 Файлы будут сохранены в папку: {save_dir}\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(**PLAYWRIGHT_CONTEXT_KWARGS)
        page = await context.new_page()

        try:
            await page.goto(doc_url, wait_until="domcontentloaded", timeout=60000)
            
            await page.wait_for_timeout(1500)
            await page.keyboard.press('Escape')
            
            print("⏳ Ждем подгрузки таблицы файлов...")
            await page.wait_for_timeout(3000)
            
            links = await page.locator('a[title="Скачать"], a[href*="attachment"], a[href*="download"]').all()
            
            unique_links = set()
            downloaded_count = 0
            
            for link in links:
                href = await link.get_attribute('href')
                
                # ФИЛЬТР: Отсекаем ссылки на подписи (signview/listModal) и системные скрипты
                if not href or 'signview' in href or 'listModal' in href or 'printForm' in href or 'javascript' in href:
                    continue
                    
                if href not in unique_links:
                    unique_links.add(href)
                    
                    # Достаем название
                    title = await link.get_attribute('title') or "Документ"
                    parent = await link.evaluate_handle('node => node.parentElement.parentElement')
                    if parent:
                        try:
                            full_text = await parent.inner_text()
                            title = full_text.split('\n')[0][:100]
                        except:
                            pass
                            
                    # Очищаем название от спецсимволов, чтобы Windows не ругалась при сохранении
                    safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c in ' -_']).strip()
                    
                    full_url = href if href.startswith('http') else f"https://zakupki.gov.ru{href}"
                    print(f"⬇️ Качаем: {safe_title}")
                    
                    # СКАЧИВАЕМ ФАЙЛ через curl_cffi (чтобы обойти защиту)
                    try:
                        response = curl_requests.get(
                            full_url, 
                            impersonate="chrome120", 
                            verify=False, # Игнорируем отсутствие сертификатов Минцифры
                            timeout=60
                        )
                        
                        if response.status_code == 200:
                            # Пытаемся вытащить оригинальное расширение файла из ответа ЕИС
                            content_disp = response.headers.get('Content-Disposition', '')
                            ext = ".doc" # Расширение по умолчанию
                            if 'filename=' in content_disp:
                                # Парсим название из заголовка (например: filename="TZ.docx")
                                filename = content_disp.split('filename=')[1].strip('"\'')
                                ext = os.path.splitext(filename)[1]
                            
                            file_path = os.path.join(save_dir, f"{safe_title}{ext}")
                            
                            # Сохраняем байты на диск
                            with open(file_path, "wb") as f:
                                f.write(response.content)
                                
                            print(f"✅ Сохранено: {file_path}\n")
                            downloaded_count += 1
                        else:
                            print(f"❌ Ошибка ЕИС при отдаче файла: {response.status_code}\n")
                    except Exception as dl_e:
                        print(f"❌ Сбой сети при скачивании: {dl_e}\n")
                        
            print(f"🎯 Итого успешно скачано файлов: {downloaded_count}")

        except Exception as e:
            print(f"❌ Ошибка парсинга: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    test_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0103200008426002414"
    test_id = "0103200008426002414"
    asyncio.run(get_tender_docs(test_url, test_id))
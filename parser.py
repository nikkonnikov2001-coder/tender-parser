import asyncio

import load_env  # noqa: F401 — .env до чтения eis_config
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from pydantic import BaseModel, HttpUrl

from browser_ctx import PLAYWRIGHT_CONTEXT_KWARGS, playwright_headless
from playwright_retry import goto_with_retry
from eis_config import (
    build_eis_results_url,
    get_eis_districts_query_value,
    get_eis_max_pages,
    get_eis_search_query,
)

class TenderItem(BaseModel):
    tender_id: str
    price: str
    name: str
    url: HttpUrl

def _parse_blocks_to_tenders(html: str) -> list[TenderItem]:
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.find_all("div", class_="search-registry-entry-block")
    out: list[TenderItem] = []
    for block in blocks:
        id_tag = block.find("div", class_="registry-entry__header-mid__number")
        tender_id = id_tag.text.strip().replace("№ ", "") if id_tag else "N/A"
        if tender_id == "N/A":
            continue
        link_tag = id_tag.find("a") if id_tag else None
        href = (
            "https://zakupki.gov.ru" + link_tag["href"]
            if link_tag and "href" in link_tag.attrs
            else "https://zakupki.gov.ru"
        )
        price_tag = block.find("div", class_="price-block__value")
        price = price_tag.text.strip().replace("\xa0", " ") if price_tag else "N/A"
        name_tag = block.find("div", class_="registry-entry__body-value")
        name = name_tag.text.strip() if name_tag else "N/A"
        try:
            out.append(
                TenderItem(tender_id=tender_id, price=price, name=name, url=href)
            )
        except Exception:
            pass
    return out


async def parse_tenders_heavy():
    districts = get_eis_districts_query_value()
    max_pages = get_eis_max_pages()
    query_preview = get_eis_search_query()
    print(
        "🚀 Поиск ЕИС: запрос — "
        f"«{query_preview}»; страниц результатов: до {max_pages}; "
        f"districts={districts} (коды округов из EIS_DISTRICT_IDS или дефолт eis_config) …"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=playwright_headless())
        context = await browser.new_context(**PLAYWRIGHT_CONTEXT_KWARGS)
        page = await context.new_page()
        tenders_list: list[TenderItem] = []
        seen_ids: set[str] = set()

        try:
            for pnum in range(1, max_pages + 1):
                url = build_eis_results_url(pnum)
                print(f"⏳ Страница результатов {pnum}/{max_pages}…")
                await goto_with_retry(
                    page, url, wait_until="domcontentloaded", timeout=60000
                )
                await page.wait_for_timeout(2000)
                await page.keyboard.press("Escape")

                try:
                    await page.wait_for_selector(
                        "div.search-registry-entry-block", timeout=30000
                    )
                except Exception:
                    if pnum == 1:
                        raise
                    print(f"   (нет карточек на стр. {pnum} — конец выдачи)")
                    break

                html = await page.content()
                page_tenders = _parse_blocks_to_tenders(html)
                if not page_tenders:
                    if pnum == 1:
                        print("⚠️ На первой странице нет карточек тендеров.")
                    break
                new_count = 0
                for t in page_tenders:
                    if t.tender_id in seen_ids:
                        continue
                    seen_ids.add(t.tender_id)
                    tenders_list.append(t)
                    new_count += 1
                print(f"   +{new_count} новых (всего уникальных: {len(tenders_list)})")
                if pnum < max_pages:
                    await asyncio.sleep(1.5)

            print(f"\n🎯 Итого уникальных тендеров: {len(tenders_list)}\n")
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
import asyncio
import logging

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

log = logging.getLogger("tender_bot.parser")

class TenderItem(BaseModel):
    tender_id: str
    price: str
    name: str
    url: HttpUrl
    pub_date: str = "—"
    org_name: str = "—"


def parse_blocks_to_tenders(html: str) -> list[TenderItem]:
    """Извлекает тендеры из HTML страницы результатов ЕИС."""
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
        date_tag = block.find("div", class_="data-block__value")
        pub_date = date_tag.text.strip() if date_tag else "—"
        org_tag = block.find("div", class_="registry-entry__body-href")
        org_name = org_tag.text.strip() if org_tag else "—"
        try:
            out.append(TenderItem(
                tender_id=tender_id, price=price, name=name, url=href,
                pub_date=pub_date, org_name=org_name,
            ))
        except Exception:
            log.warning(
                "Невалидная карточка тендера %s (url=%s): пропущена",
                tender_id, href,
            )
    return out


async def fetch_and_parse_page(page, url: str) -> list[TenderItem]:
    """Переходит по URL, ждёт карточки и возвращает распарсенные тендеры."""
    await goto_with_retry(page, url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2000)
    await page.keyboard.press("Escape")
    await page.wait_for_selector("div.search-registry-entry-block", timeout=30000)
    html = await page.content()
    return parse_blocks_to_tenders(html)


async def parse_tenders_heavy():
    districts = get_eis_districts_query_value()
    max_pages = get_eis_max_pages()
    query_preview = get_eis_search_query()
    log.info(
        "Поиск ЕИС: запрос «%s», страниц: %d, districts=%s",
        query_preview, max_pages, districts,
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
                log.info("Страница результатов %d/%d...", pnum, max_pages)
                try:
                    page_tenders = await fetch_and_parse_page(page, url)
                except Exception:
                    if pnum == 1:
                        raise
                    log.info("Нет карточек на стр. %d — конец выдачи", pnum)
                    break

                if not page_tenders:
                    if pnum == 1:
                        log.warning("На первой странице нет карточек тендеров.")
                    break
                new_count = 0
                for t in page_tenders:
                    if t.tender_id in seen_ids:
                        continue
                    seen_ids.add(t.tender_id)
                    tenders_list.append(t)
                    new_count += 1
                log.info("+%d новых (всего уникальных: %d)", new_count, len(tenders_list))
                if pnum < max_pages:
                    await asyncio.sleep(1.5)

            log.info("Итого уникальных тендеров: %d", len(tenders_list))
            for t in tenders_list:
                log.info("ID: %s | %s", t.tender_id, t.price)
            return tenders_list

        except Exception as e:
            log.error("Ошибка загрузки: %s", e)
            try:
                await page.screenshot(path="error_screenshot.png")
            except Exception:
                pass
            if tenders_list:
                log.warning(
                    "Возвращаем %d частично собранных тендеров.",
                    len(tenders_list),
                )
                return tenders_list
            return []
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(parse_tenders_heavy())
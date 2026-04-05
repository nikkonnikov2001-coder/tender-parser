import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse, urlunparse

from curl_cffi import requests as curl_requests
from playwright.async_api import Page, async_playwright

from browser_ctx import PLAYWRIGHT_CONTEXT_KWARGS, playwright_headless
from playwright_retry import goto_with_retry

log = logging.getLogger("tender_bot.downloader")

_VERIFY_TLS = os.environ.get(
    "DOWNLOAD_VERIFY_TLS", "1"
).strip().lower() not in ("0", "false", "no", "off")


def _documents_page_url(tender_url: str) -> str:
    """Страница «Документы» для карточки закупки (разные шаблоны путей на ЕИС)."""
    u = (tender_url or "").strip()
    if not u:
        return u
    if "documents.html" in u:
        return u
    if "common-info.html" in u:
        return u.replace("common-info.html", "documents.html")
    # .../view/view.html?... → documents.html с тем же query
    if "view.html" in u:
        return u.replace("view.html", "documents.html")
    parsed = urlparse(u)
    path = parsed.path or ""
    if path.rstrip("/").endswith("/view"):
        new_path = path.rstrip("/") + "/documents.html"
        return urlunparse(parsed._replace(path=new_path))
    if re.search(r"/view/[^/?]+\.html$", path):
        new_path = re.sub(r"/[^/]+\.html$", "/documents.html", path)
        return urlunparse(parsed._replace(path=new_path))
    return u


def _allocate_download_path(save_dir: str, base_stem: str, ext: str) -> str:
    """Не затираем файлы с одинаковым нормализованным именем."""
    ext = ext if ext.startswith(".") else f".{ext}"
    candidate = os.path.join(save_dir, f"{base_stem}{ext}")
    if not os.path.isfile(candidate):
        return candidate
    n = 2
    while True:
        alt = os.path.join(save_dir, f"{base_stem}_{n}{ext}")
        if not os.path.isfile(alt):
            return alt
        n += 1


@asynccontextmanager
async def shared_download_browser() -> AsyncIterator[Page]:
    """Один Chromium на серию тендеров (меньше накладных расходов, чем launch на каждый ID)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=playwright_headless())
        context = await browser.new_context(**PLAYWRIGHT_CONTEXT_KWARGS)
        page = await context.new_page()
        try:
            yield page
        finally:
            await browser.close()


async def get_tender_docs(
    page: Page, url: str, tender_id: str, base_dir: str = "downloads",
) -> None:
    doc_url = _documents_page_url(url)
    log.info("Раздел документов: %s", doc_url)

    save_dir = os.path.join(base_dir, tender_id)
    os.makedirs(save_dir, exist_ok=True)
    log.info("Сохранение в: %s", save_dir)

    try:
        await goto_with_retry(
            page, doc_url, wait_until="domcontentloaded", timeout=60000
        )

        await page.wait_for_timeout(1500)
        await page.keyboard.press("Escape")

        log.debug("Ожидание подгрузки таблицы файлов...")
        await page.wait_for_timeout(3000)

        links = await page.locator(
            'a[title="Скачать"], a[href*="attachment"], a[href*="download"]'
        ).all()

        unique_links: set[str] = set()
        downloaded_count = 0

        for link in links:
            href = await link.get_attribute("href")

            if not href or "signview" in href or "listModal" in href or "printForm" in href or "javascript" in href:
                continue

            if href in unique_links:
                continue
            unique_links.add(href)

            title = await link.get_attribute("title") or "Документ"
            parent = await link.evaluate_handle("node => node.parentElement.parentElement")
            if parent:
                try:
                    full_text = await parent.inner_text()
                    title = full_text.split("\n")[0][:100]
                except Exception:
                    pass

            safe_title = "".join(
                [c for c in title if c.isalpha() or c.isdigit() or c in " -_"]
            ).strip()

            full_url = href if href.startswith("http") else f"https://zakupki.gov.ru{href}"
            log.info("Скачивание: %s", safe_title)

            try:
                response = curl_requests.get(
                    full_url,
                    impersonate="chrome120",
                    verify=_VERIFY_TLS,
                    timeout=60,
                )

                if response.status_code == 200:
                    content_disp = response.headers.get("Content-Disposition", "")
                    ext = ".doc"
                    if "filename=" in content_disp:
                        filename = content_disp.split("filename=")[1].strip("\"'")
                        ext = os.path.splitext(filename)[1]

                    file_path = _allocate_download_path(
                        save_dir, safe_title or "document", ext
                    )

                    with open(file_path, "wb") as f:
                        f.write(response.content)

                    log.info("Сохранено: %s", file_path)
                    downloaded_count += 1
                else:
                    log.warning("Ошибка ЕИС при отдаче файла: %s", response.status_code)
            except Exception as dl_e:
                log.warning("Сбой сети при скачивании: %s", dl_e)

        log.info("Итого скачано файлов: %d", downloaded_count)

    except Exception as e:
        log.error("Ошибка при скачивании документов: %s", e)


async def _get_tender_docs_one_off(url: str, tender_id: str) -> None:
    async with shared_download_browser() as page:
        await get_tender_docs(page, url, tender_id)


if __name__ == "__main__":
    test_url = "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber=0103200008426002414"
    test_id = "0103200008426002414"
    asyncio.run(_get_tender_docs_one_off(test_url, test_id))
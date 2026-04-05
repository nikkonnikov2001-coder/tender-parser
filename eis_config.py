"""Параметры расширенного поиска zakupki.gov.ru (results.html).

СФО — Сибирский федеральный округ; «Поволжье» в фильтрах ЕИС соответствует
Приволжскому федеральному округу (ПФО), не путать с Уральским (УФО).

Коды округов — НСИ ЕИС; при расхождении скопируйте `districts` из URL в EIS_DISTRICT_IDS.
"""

import os
from urllib.parse import quote_plus

# Сибирский и Приволжский федеральные округа (типовые коды НСИ).
SIBERIAN_FD = "5277325"
PRIVOLZHSKY_FD = "5277323"

_ALLOWED_PAGE_SIZES = (10, 20, 50, 100)


def get_eis_districts_query_value() -> str:
    """Значение для `districts=...` (ID через запятую, для URL — заменить `,` на `%2C`)."""
    raw = os.getenv("EIS_DISTRICT_IDS", "").strip()
    if raw:
        return ",".join(part.strip() for part in raw.split(",") if part.strip())
    return f"{SIBERIAN_FD},{PRIVOLZHSKY_FD}"


def get_eis_search_query() -> str:
    q = os.getenv("EIS_SEARCH_QUERY", "организация мероприятий").strip()
    return q or "организация мероприятий"


def get_eis_price_from() -> int:
    try:
        return int(os.getenv("EIS_PRICE_FROM", "5000000"))
    except ValueError:
        return 5_000_000


def get_eis_price_to() -> int:
    try:
        return int(os.getenv("EIS_PRICE_TO", "30000000"))
    except ValueError:
        return 30_000_000


def get_eis_records_per_page_token() -> str:
    """ЕИС ожидает recordsPerPage=_10 / _50 и т.д."""
    try:
        n = int(os.getenv("EIS_RECORDS_PER_PAGE", "50"))
    except ValueError:
        n = 50
    if n not in _ALLOWED_PAGE_SIZES:
        n = 50
    return f"_{n}"


def get_eis_max_pages() -> int:
    try:
        n = int(os.getenv("EIS_MAX_PAGES", "1"))
    except ValueError:
        n = 1
    return max(1, min(n, 50))


def build_eis_url(
    *,
    search_query: str,
    page_number: int = 1,
    records_per_page: str = "_50",
    sort_by: str = "UPDATE_DATE",
    sort_direction: str = "false",
    laws: list[str] | None = None,
    price_from: int = 5_000_000,
    price_to: int = 30_000_000,
    districts: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    customer_title: str = "",
    placing_ways: list[str] | None = None,
    order_stages: list[str] | None = None,
) -> str:
    """Единый URL-билдер для расширенного поиска ЕИС."""
    page_number = max(1, page_number)
    search_enc = quote_plus(search_query)

    parts = [
        "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?",
        f"searchString={search_enc}",
        "&morphology=on",
        "&search-filter=Дате+размещения",
        f"&pageNumber={page_number}",
        f"&sortDirection={sort_direction}",
        f"&recordsPerPage={records_per_page}",
        "&showLotsInfoHidden=false",
        f"&sortBy={sort_by}",
    ]

    for law in (laws or ["fz44", "fz223", "af"]):
        parts.append(f"&{law}=on")

    parts.append("&currencyIdGeneral=-1")
    parts.append(f"&priceFromGeneral={price_from}")
    parts.append(f"&priceToGeneral={price_to}")

    if districts:
        parts.append(f"&districts={districts.replace(',', '%2C')}")
    if date_from:
        parts.append(f"&publishDateFrom={date_from}")
    if date_to:
        parts.append(f"&publishDateTo={date_to}")
    if customer_title:
        parts.append(f"&customerTitle={quote_plus(customer_title)}")
    if placing_ways:
        parts.append(f"&placingWayList={'%2C'.join(placing_ways)}")
    if order_stages:
        parts.append(f"&orderStages={'%2C'.join(order_stages)}")

    return "".join(parts)


def build_eis_results_url(page_number: int) -> str:
    """CLI-обёртка: собирает параметры из env и вызывает build_eis_url."""
    return build_eis_url(
        search_query=get_eis_search_query(),
        page_number=page_number,
        records_per_page=get_eis_records_per_page_token(),
        price_from=get_eis_price_from(),
        price_to=get_eis_price_to(),
        districts=get_eis_districts_query_value(),
    )

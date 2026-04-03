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


def build_eis_results_url(page_number: int) -> str:
    districts = get_eis_districts_query_value().replace(",", "%2C")
    search_enc = quote_plus(get_eis_search_query())
    pf = get_eis_price_from()
    pt = get_eis_price_to()
    rpp = get_eis_records_per_page_token()
    page_number = max(1, page_number)
    return (
        "https://zakupki.gov.ru/epz/order/extendedsearch/results.html?"
        f"searchString={search_enc}&morphology=on&search-filter=Дате+размещения"
        f"&pageNumber={page_number}&sortDirection=false&recordsPerPage={rpp}&showLotsInfoHidden=false"
        "&sortBy=UPDATE_DATE&fz44=on&fz223=on&af=on&currencyIdGeneral=-1"
        f"&priceFromGeneral={pf}&priceToGeneral={pt}&districts={districts}"
    )

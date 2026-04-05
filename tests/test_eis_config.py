from eis_config import build_eis_url


def test_basic_url_structure():
    url = build_eis_url(
        search_query="тест",
        page_number=1,
        price_from=1_000_000,
        price_to=5_000_000,
    )
    assert "zakupki.gov.ru" in url
    assert "pageNumber=1" in url
    assert "priceFromGeneral=1000000" in url
    assert "priceToGeneral=5000000" in url


def test_laws_in_url():
    url = build_eis_url(
        search_query="тест",
        laws=["fz44"],
    )
    assert "fz44=on" in url
    assert "fz223=on" not in url


def test_districts_comma_encoding():
    url = build_eis_url(
        search_query="тест",
        districts="111,222",
    )
    assert "districts=111%2C222" in url


def test_page_number_min_1():
    url = build_eis_url(search_query="тест", page_number=0)
    assert "pageNumber=1" in url


def test_optional_filters():
    url = build_eis_url(
        search_query="тест",
        date_from="01.01.2026",
        date_to="31.03.2026",
        customer_title="Минобороны",
        placing_ways=["EA44", "OK44"],
        order_stages=["AF"],
    )
    assert "publishDateFrom=01.01.2026" in url
    assert "publishDateTo=31.03.2026" in url
    assert "customerTitle=" in url
    assert "placingWayList=EA44%2COK44" in url
    assert "orderStages=AF" in url

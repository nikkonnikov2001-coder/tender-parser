from parser import parse_blocks_to_tenders


SAMPLE_HTML = """
<div class="search-registry-entry-block">
  <div class="registry-entry__header-mid__number">
    <a href="/epz/order/notice/ea20/view/common-info.html?regNumber=0123456789">
      № 0123456789
    </a>
  </div>
  <div class="price-block__value">1 500 000,00 ₽</div>
  <div class="registry-entry__body-value">Поставка оборудования</div>
  <div class="data-block__value">01.04.2026</div>
  <div class="registry-entry__body-href">ООО Рога и Копыта</div>
</div>
"""


def test_parse_single_tender():
    tenders = parse_blocks_to_tenders(SAMPLE_HTML)
    assert len(tenders) == 1
    t = tenders[0]
    assert t.tender_id == "0123456789"
    assert "1 500 000" in t.price
    assert t.name == "Поставка оборудования"
    assert t.pub_date == "01.04.2026"
    assert t.org_name == "ООО Рога и Копыта"
    assert "0123456789" in str(t.url)


def test_parse_empty_html():
    assert parse_blocks_to_tenders("<html></html>") == []


def test_parse_block_without_id():
    html = '<div class="search-registry-entry-block"><div>no id</div></div>'
    assert parse_blocks_to_tenders(html) == []

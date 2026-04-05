import pytest
from tz_docs import is_tz_file, _has_tz_marker


@pytest.mark.parametrize("filename,expected", [
    ("Техническое_задание_v2.docx", True),
    ("ТЗ на поставку.pdf", True),
    ("проект_контракта.doc", True),
    ("техзадание.rtf", True),
    ("описание_объекта_закупки.docx", True),
    ("задание_на_проектирование.pdf", True),
    ("Накладная_оплата.docx", False),
    ("readme.txt", False),
    ("фото.png", False),
    ("контракт.xlsx", False),
    ("ТЗ на поставку.txt", False),
])
def test_is_tz_file(filename, expected):
    assert is_tz_file(filename) == expected


def test_has_tz_marker_case_insensitive():
    assert _has_tz_marker("ТЕХНИЧЕСКОЕ_ЗАДАНИЕ.PDF")
    assert _has_tz_marker("тз_v3.docx")
    assert not _has_tz_marker("invoice.docx")

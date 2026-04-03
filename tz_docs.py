"""Единые правила: какие файлы считаем ТЗ (.docx / .pdf)."""

TZ_NAME_MARKERS = (
    "тз",
    "техническое_задание",
    "техзадание",
    "описание_объекта",
    "контракт",
    "проект_контракта",
    "задание",
)


def is_tz_docx(filename: str) -> bool:
    if not filename.lower().endswith(".docx"):
        return False
    lower = filename.lower()
    return any(marker in lower for marker in TZ_NAME_MARKERS)


def is_tz_pdf(filename: str) -> bool:
    if not filename.lower().endswith(".pdf"):
        return False
    lower = filename.lower()
    return any(marker in lower for marker in TZ_NAME_MARKERS)

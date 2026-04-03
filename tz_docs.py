"""Единые правила: какие файлы считаем ТЗ (.docx)."""

TZ_NAME_MARKERS = (
    "тз",
    "техническое_задание",
    "описание_объекта",
    "контракт",
)


def is_tz_docx(filename: str) -> bool:
    if not filename.lower().endswith(".docx"):
        return False
    lower = filename.lower()
    return any(marker in lower for marker in TZ_NAME_MARKERS)

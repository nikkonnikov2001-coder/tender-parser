"""Единые правила: какие файлы считаем ТЗ (.docx / .doc / .pdf / .rtf)."""

TZ_NAME_MARKERS = (
    "тз",
    "техническое_задание",
    "техзадание",
    "описание_объекта",
    "контракт",
    "проект_контракта",
    "задание",
)

_SUPPORTED_EXTENSIONS = (".docx", ".doc", ".pdf", ".rtf")


def _has_tz_marker(filename: str) -> bool:
    lower = filename.lower()
    return any(marker in lower for marker in TZ_NAME_MARKERS)


def is_tz_docx(filename: str) -> bool:
    return filename.lower().endswith(".docx") and _has_tz_marker(filename)


def is_tz_doc(filename: str) -> bool:
    low = filename.lower()
    return low.endswith(".doc") and not low.endswith(".docx") and _has_tz_marker(filename)


def is_tz_pdf(filename: str) -> bool:
    return filename.lower().endswith(".pdf") and _has_tz_marker(filename)


def is_tz_rtf(filename: str) -> bool:
    return filename.lower().endswith(".rtf") and _has_tz_marker(filename)


def is_tz_file(filename: str) -> bool:
    """Проверяет, подходит ли файл по имени и расширению как ТЗ."""
    low = filename.lower()
    return any(low.endswith(ext) for ext in _SUPPORTED_EXTENSIONS) and _has_tz_marker(filename)

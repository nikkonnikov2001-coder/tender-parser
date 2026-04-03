"""OCR для PDF без текстового слоя (сканы): PyMuPDF → изображение страницы → Tesseract."""

from __future__ import annotations

import io
import os

import fitz  # PyMuPDF
import pytesseract
from PIL import Image


def _tesseract_cmd() -> None:
    cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd


def _pdf_ocr_dpi() -> int:
    try:
        n = int(os.environ.get("PDF_OCR_DPI", "200"))
    except ValueError:
        n = 200
    return max(72, min(n, 400))


def _pdf_ocr_max_pages() -> int:
    try:
        n = int(os.environ.get("PDF_OCR_MAX_PAGES", "30"))
    except ValueError:
        n = 30
    return max(1, min(n, 200))


def _pdf_ocr_lang() -> str:
    return (os.environ.get("PDF_OCR_LANG", "rus+eng").strip() or "rus+eng")


def extract_pdf_text_via_ocr(file_path: str) -> str:
    """
    Растеризация страниц PDF и распознавание через Tesseract.
    Нужен установленный Tesseract (+ языки rus, eng для rus+eng).
    """
    _tesseract_cmd()
    dpi = _pdf_ocr_dpi()
    max_pages = _pdf_ocr_max_pages()
    lang = _pdf_ocr_lang()
    scale = dpi / 72.0
    mat = fitz.Matrix(scale, scale)

    doc = fitz.open(file_path)
    try:
        n = min(doc.page_count, max_pages)
        parts: list[str] = []
        for i in range(n):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                chunk = pytesseract.image_to_string(img, lang=lang)
            except pytesseract.TesseractNotFoundError:
                raise RuntimeError(
                    "Tesseract не найден в PATH. Установите Tesseract OCR "
                    "(Windows: https://github.com/UB-Mannheim/tesseract/wiki) "
                    "или укажите путь в TESSERACT_CMD."
                ) from None
            except Exception:
                chunk = ""
            if chunk and chunk.strip():
                parts.append(chunk.strip())
        return "\n".join(parts)
    finally:
        doc.close()

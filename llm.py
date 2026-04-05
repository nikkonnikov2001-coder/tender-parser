"""
Единый модуль для вызова Ollama LLM.
Используется и CLI (analyzer.py), и ботом (bot_search.py).
"""

import os
import logging

import load_env  # noqa: F401
import requests

log = logging.getLogger("tender_bot.llm")

OLLAMA_URL = os.environ.get(
    "OLLAMA_URL", "http://localhost:11434/api/generate"
).strip()

DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b").strip()

try:
    OLLAMA_TIMEOUT_SEC = int(os.environ.get("OLLAMA_TIMEOUT_SEC", "600"))
except ValueError:
    OLLAMA_TIMEOUT_SEC = 600

MAX_TEXT_CHARS = 25_000

PROMPT_TEMPLATE = (
    "Ты — профессиональный тендерный аналитик. "
    "Прочитай выдержку из Технического задания (ТЗ) и составь "
    "выжимку без воды.\n\n"
    "Структура ответа:\n"
    "1. Предмет контракта: (Что нужно сделать)\n"
    "2. Сроки: (Даты)\n"
    "3. Требования и штрафы: (Важные условия)\n\n"
    "Текст ТЗ:\n{text}"
)


class OllamaError(Exception):
    """Ошибка при обращении к Ollama API."""


def call_ollama(text: str, tender_id: str, model: str | None = None) -> str:
    model = model or DEFAULT_MODEL
    safe_text = text[:MAX_TEXT_CHARS]

    log.info(
        "LLM %s, тендер %s (%d симв.)", model, tender_id, len(safe_text),
    )

    prompt = PROMPT_TEMPLATE.format(text=safe_text)

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 16384},
        }, timeout=OLLAMA_TIMEOUT_SEC)
    except Exception as e:
        raise OllamaError(f"Сбой сети: {e}") from e

    if resp.status_code != 200:
        raise OllamaError(f"API вернул {resp.status_code}: {resp.text[:200]}")

    return resp.json().get("response", "")

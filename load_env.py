"""Подхватывает .env из корня проекта при импорте (безопасно вызывать из любого entrypoint)."""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

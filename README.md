# Тендерный AI-бот

Telegram-бот для автоматического мониторинга и AI-анализа государственных закупок на [zakupki.gov.ru](https://zakupki.gov.ru).

## Возможности

- **Поиск тендеров** — парсинг ЕИС по ключевым словам, цене, регионам, законам, заказчику, способу закупки, этапу размещения
- **Скачивание ТЗ** — автоматическая загрузка документации (.docx, .doc, .pdf, .rtf)
- **AI-анализ** — Ollama читает ТЗ и выделяет предмет контракта, сроки, штрафы
- **Excel-отчёт** — аналитическая таблица с результатами, прямо в чат
- **Мониторинг** — автоматическая проверка новых тендеров по расписанию с дедупликацией
- **Multi-user** — каждый пользователь получает свои настройки, историю, downloads и Excel
- **Контроль доступа** — allowlist + админ-панель для управления пользователями

## Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
playwright install chromium
```

Дополнительно (опционально):
- **LibreOffice** — для чтения `.doc` файлов
- **Tesseract** — для OCR сканированных PDF

### 2. Настройка .env

```bash
cp .env.example .env
# Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID
```

### 3. Запуск Ollama (для AI-анализа)

```bash
ollama pull qwen2.5:7b
ollama serve
```

### 4. Запуск бота

```bash
python bot.py
```

### 5. CLI-режим (без Telegram)

```bash
python main.py                # полный цикл: поиск → скачивание → анализ → отчёт
python main.py download-only  # только поиск и скачивание
python main.py analyze-only   # только анализ + Excel
```

## Структура проекта

```
├── bot.py               # Telegram-бот (меню, обработчики, мониторинг, allowlist)
├── bot_config.py         # Per-user настройки (JSON в bot_settings/)
├── bot_search.py         # Конвейер поиска с прогрессом в Telegram
├── main.py               # CLI-пайплайн
├── parser.py             # Парсер результатов zakupki.gov.ru (Playwright)
├── downloader.py         # Скачивание документов из карточки тендера
├── reader.py             # Извлечение текста из .docx/.doc/.pdf/.rtf
├── tz_docs.py            # Определение файлов ТЗ по имени/расширению
├── llm.py                # Единый модуль вызова Ollama LLM
├── analyzer.py           # AI-анализ ТЗ + Excel (CLI)
├── notifier.py           # Отправка отчёта в Telegram (CLI)
├── browser_ctx.py        # Настройки Playwright (UA, viewport, headless)
├── playwright_retry.py   # Retry-обёртка для навигации
├── eis_config.py         # URL-билдер для CLI-поиска
├── pdf_ocr.py            # OCR для сканированных PDF
├── load_env.py           # Загрузка .env
├── requirements.txt      # Python-зависимости
└── .env.example          # Шаблон переменных окружения
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Главное меню |
| `/search` | Запустить поиск |
| `/settings` | Настройки поиска |
| `/monitor` | Управление мониторингом |
| `/stats` | Статистика |
| `/help` | Справка |
| `/allow ID` | Добавить пользователя (админ) |
| `/deny ID` | Удалить пользователя (админ) |
| `/users` | Список пользователей (админ) |

## Технологии

- **Python 3.11+**
- **aiogram 3** — Telegram Bot API
- **Playwright** — headless-браузер для парсинга ЕИС
- **BeautifulSoup + lxml** — парсинг HTML
- **Ollama** — локальная LLM для анализа документов
- **pandas + openpyxl** — формирование Excel
- **APScheduler** — планировщик для мониторинга
- **curl_cffi** — HTTP-клиент с Chrome-импersonацией

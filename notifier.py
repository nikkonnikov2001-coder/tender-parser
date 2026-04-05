import logging
import os

from load_env import build_telegram_proxy_url  # noqa: F401 (side-effect: loads .env)
import requests

log = logging.getLogger("tender_bot.notifier")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def _telegram_proxies():
    url = build_telegram_proxy_url()
    if not url:
        return None
    return {"http": url, "https": url}


def send_telegram_report(file_path):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Не заданы TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID — пропускаем отправку.")
        return

    if not os.path.exists(file_path):
        log.error("Файл %s не найден!", file_path)
        return

    proxies = _telegram_proxies()
    log.info("Отправляем отчёт в Telegram%s...", " через прокси" if proxies else "")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"

    with open(file_path, "rb") as f:
        files = {"document": f}
        data = {
            "chat_id": CHAT_ID,
            "caption": "Свежая аналитика по тендерам готова!",
        }

        try:
            response = requests.post(
                url, files=files, data=data, proxies=proxies, timeout=120
            )

            if response.status_code == 200:
                log.info("Отчет успешно доставлен в Telegram.")
            else:
                log.error("Ошибка Telegram API: %s", response.text)

        except Exception as e:
            err = str(e)
            log.error("Сбой сети при отправке: %s", e)
            if "407" in err or "Proxy Authentication" in err:
                log.error(
                    "407 = прокси не принял логин/пароль. "
                    "Проверьте TELEGRAM_PROXY_* в .env."
                )


if __name__ == "__main__":
    from analyzer import EXCEL_FILENAME

    send_telegram_report(EXCEL_FILENAME)

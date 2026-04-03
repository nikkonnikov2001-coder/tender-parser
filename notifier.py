import os
from typing import Optional
from urllib.parse import quote

import load_env  # noqa: F401
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def _build_proxy_url() -> Optional[str]:
    """
    Прокси для requests: либо TELEGRAM_PROXY_* (предпочтительно — пароль с любыми символами),
    либо TELEGRAM_HTTP_PROXY_URL как есть.
    """
    host = os.environ.get("TELEGRAM_PROXY_HOST", "").strip()
    port = os.environ.get("TELEGRAM_PROXY_PORT", "").strip()
    user = os.environ.get("TELEGRAM_PROXY_USER", "").strip()
    password = os.environ.get("TELEGRAM_PROXY_PASSWORD", "").strip()
    raw_url = os.environ.get("TELEGRAM_HTTP_PROXY_URL", "").strip()

    if host and port:
        if user or password:
            u = quote(user, safe="")
            p = quote(password, safe="")
            return f"http://{u}:{p}@{host}:{port}"
        return f"http://{host}:{port}"

    return raw_url or None


def _telegram_proxies():
    url = _build_proxy_url()
    if not url:
        return None
    return {"http": url, "https": url}


def send_telegram_report(file_path):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Не заданы TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID в .env — пропускаем отправку.")
        return

    if not os.path.exists(file_path):
        print(f"❌ Ошибка: Файл {file_path} не найден!")
        return

    proxies = _telegram_proxies()
    if proxies:
        print("\n🚀 Отправляем отчёт в Telegram через прокси...")
    else:
        print("\n🚀 Отправляем отчёт в Telegram (без прокси)...")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"

    with open(file_path, "rb") as f:
        files = {"document": f}
        data = {
            "chat_id": CHAT_ID,
            "caption": (
                "🔥 Брух, свежая аналитика по тендерам готова! "
                "Твоя RTX 3070 отлично потрудилась."
            ),
        }

        try:
            response = requests.post(
                url, files=files, data=data, proxies=proxies, timeout=120
            )

            if response.status_code == 200:
                print("✅ Отчет успешно доставлен в Телегу!")
            else:
                print(f"❌ Ошибка Телеграма: {response.text}")

        except Exception as e:
            err = str(e)
            print(f"❌ Сбой сети при отправке.\nОшибка: {e}")
            if "407" in err or "Proxy Authentication" in err:
                print(
                    "\n💡 407 = прокси не принял логин/пароль. "
                    "Заполни в .env TELEGRAM_PROXY_HOST, TELEGRAM_PROXY_PORT, "
                    "TELEGRAM_PROXY_USER, TELEGRAM_PROXY_PASSWORD (без ручного URL) "
                    "или проверь данные у провайдера."
                )


if __name__ == "__main__":
    from analyzer import EXCEL_FILENAME

    send_telegram_report(EXCEL_FILENAME)

import os

import load_env  # noqa: F401
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
PROXY_URL = os.environ.get("TELEGRAM_HTTP_PROXY_URL", "").strip()


def _telegram_proxies():
    if not PROXY_URL:
        return None
    return {"http": PROXY_URL, "https": PROXY_URL}


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
            print(f"❌ Сбой сети при отправке.\nОшибка: {e}")


if __name__ == "__main__":
    send_telegram_report("Tenders_Analytics_DB.xlsx")

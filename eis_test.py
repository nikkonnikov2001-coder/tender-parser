from curl_cffi import requests

def test_eis_connection():
    url = "https://zakupki.gov.ru/epz/order/extendedsearch/search.html"
    
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    print("Отправляем запрос в ЕИС (таймаут 30 сек)...")
    try:
        # Увеличили таймаут до 30 и добавили заголовки
        response = requests.get(url, impersonate="chrome120", headers=headers, timeout=30)
        
        if response.status_code == 200:
            print("✅ Успех! ЕИС пустила нас.")
            print(f"Длина полученного HTML: {len(response.text)} символов.")
        else:
            print(f"❌ Ошибка или блок. Статус-код: {response.status_code}")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")

if __name__ == "__main__":
    test_eis_connection()
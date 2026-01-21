from google import genai

# ВСТАВЬ СЮДА СВОЙ КЛЮЧ
client = genai.Client(api_key="")

print("📋 Список доступных моделей:")
try:
    for m in client.models.list():
        # Просто выводим имена всех моделей, которые видит ваш ключ
        print(f"- {m.name}")
except Exception as e:
    print(f"Ошибка: {e}")

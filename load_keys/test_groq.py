import os
from dotenv import load_dotenv
from groq import Groq

# Загружаем ключи из .env
load_dotenv(".env")

try:
    # Инициализируем клиента Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    print("🔎 Получаю список активных моделей Groq...\n")

    # Запрашиваем список моделей
    models = client.models.list()

    # Выводим ID каждой модели
    for m in models.data:
        print(f"✅ {m.id}")

except Exception as e:
    print(f"❌ Ошибка: {e}")

import os
from dotenv import load_dotenv
from google import genai

# Загружаем переменные окружения из .env файла в корне проекта
# load_dotenv() автоматически найдет .env в текущей или родительской директории
load_dotenv(".env")

# Получаем ключ из переменных окружения
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("❌ ERROR: GEMINI_API_KEY not found in .env file!")
    sys.exit(1)

# Новая инициализация
client = genai.Client(api_key=GEMINI_API_KEY)

print("📋 Available models for your key:")
try:
    for m in client.models.list():
        print(f"- {m.name}")
except Exception as e:
    print(f"Error fetching models: {e}")

import logging
import os
import sys
import threading
import time

import feedparser
import requests
import schedule
import telebot
from dotenv import load_dotenv  # pip install python-dotenv
from google import genai
from groq import Groq  # pip install groq
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# Загрузка переменных окружения
load_dotenv(".env")

# ==========================================
# 🔴 НАСТРОЙКИ (КЛЮЧИ ИЗ .ENV)
# ==========================================
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

# --- Telegram ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", 0))

# --- API Ключи ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")

# --- Настройки контента ---
RSS_URLS = os.getenv("RSS_URLS", "").split(",")
KEYWORDS_INCLUDE = os.getenv("KEYWORDS_INCLUDE", "").split(",")
KEYWORDS_EXCLUDE = os.getenv("KEYWORDS_EXCLUDE", "").split(",")

# --- Настройки моделей AI ---
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-flash-latest")
GROQ_MODEL = "llama-3.3-70b-versatile" # Жестко задаем актуальную модель

# --- Файл истории ---
HISTORY_FILE = "history.txt"
# ==========================================
# ПРОВЕРКА КРИТИЧЕСКИХ ПЕРЕМЕННЫХ
# ==========================================
def validate_env_vars():
    """Проверяет наличие всех необходимых переменных окружения."""
    required_vars = {
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "CHAT_ID": CHAT_ID,
        "GEMINI_API_KEY": GEMINI_API_KEY, # Этот токен тоже важен
        "LINKEDIN_ACCESS_TOKEN": LINKEDIN_ACCESS_TOKEN, # Этот токен тоже важен
        "RSS_URLS": RSS_URLS and RSS_URLS[0], # Проверяем, что список не пустой
        "KEYWORDS_INCLUDE": KEYWORDS_INCLUDE and KEYWORDS_INCLUDE[0], # И здесь тоже
    }
    missing_vars = [key for key, value in required_vars.items() if not value]
    if missing_vars:
        logging.error(f"❌ Критическая ошибка: Отсутствуют переменные в .env: {', '.join(missing_vars)}")
        sys.exit(1)

validate_env_vars()

if not GROQ_API_KEY:
    logging.warning("⚠️ GROQ_API_KEY не найден. Бот будет работать только с Gemini.")

# ==========================================
# ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ
# ==========================================
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client_gemini = genai.Client(api_key=GEMINI_API_KEY)

# Конфигурация Gemini (google-genai подхватит ключ из окружения)
# genai.configure(api_key=GEMINI_API_KEY) # Старый метод, больше не используется
# Инициализация Groq
client_groq = None
if GROQ_API_KEY and GROQ_API_KEY.startswith("gsk_"):
    client_groq = Groq(api_key=GROQ_API_KEY)

# Глобальные переменные для хранения состояния
processed_links = set()
drafts_in_memory = {}

# ==========================================
# ЛОГИКА ПАМЯТИ (HISTORY.TXT)
# ==========================================


def load_history():
    """Загружает ссылки из файла в память при старте"""
    # Проверка, не является ли путь директорией (частая ошибка с Docker-volumes)
    if os.path.isdir(HISTORY_FILE):
        logging.error(f"❌ ОШИБКА: '{HISTORY_FILE}' является директорией. Удалите ее и перезапустите бота.")
        sys.exit(1)
    # Если файла нет, создаем его, чтобы избежать ошибок при первом запуске
    if not os.path.exists(HISTORY_FILE):
        open(HISTORY_FILE, 'a').close()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_to_history(link):
    """Дописывает новую ссылку в файл"""
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{link}\n")


# Загружаем историю при запуске
processed_links = load_history()


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def generate_image_smart(text_prompt):
    """
    [ЗАГЛУШКА] Генерирует изображение на основе текста.
    Эта функция - заглушка. Для реальной генерации нужна интеграция
    с DALL-E, Imagen, Pollinations AI или другой моделью.
    """
    logging.info(f"🖼️ [ЗАГЛУШКА] Начата генерация изображения для промпта: {text_prompt[:50]}...")
    # Здесь должен быть код для вызова API генерации изображений.
    # В данный момент функция возвращает None, чтобы показать, что картинка не была создана.
    image_path = None
    if image_path:
        logging.info(f"✅ Изображение успешно сгенерировано и сохранено: {image_path}")
    else:
        logging.warning("⚠️ Генерация изображения пропущена (функция-заглушка).")
    return image_path

def post_to_linkedin(text):
    # Сначала получаем ваш ID пользователя (URN)
    user_info = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}"},
    ).json()

    author_id = user_info.get("sub")  # Это ваш уникальный идентификатор

    # Формируем структуру поста
    post_data = {
        "author": f"urn:li:person:{author_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    # Отправляем пост
    response = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=post_data,
    )
    logging.info(f"Ответ LinkedIn: {response.status_code}, {response.text}")
    return response.status_code == 201


def is_relevant(text):
    text_lower = text.lower()
    if any(word.lower() in text_lower for word in KEYWORDS_EXCLUDE):
        return False
    if any(word.lower() in text_lower for word in KEYWORDS_INCLUDE):
        return True
    return False


# 1. Единый Промпт для всех нейросетей
def create_prompt(title, summary, link):
    return f"""
    ROLE:
    You are Roman, a passionate Junior SOC Analyst from the Heilbronn region (Germany). You are a Master's student, a cybersecurity geek, and you constantly monitor news.

    TASK:
    Retell the provided technical news for LinkedIn as if you are sitting in a pub with IT friends in the evening, telling them this story with burning eyes.

    🚫 NEGATIVE CONSTRAINTS (STRICTLY FORBIDDEN):
    1. NO SLANG: Do NOT use words like "krass", "krank", "Wahnsinn", "Leute".
    2. NO CHILDISH LANGUAGE: Do NOT use "schlechte Projekte" or "böse Hacker".
       -> INSTEAD USE: "manipulierte Projekte", "schadcode-infizierte Add-ons", "kriminelle Akteure".
    3. NO TAUTOLOGIES: Do NOT write "kostenlose oder kostenlose". Check for repetitive logic within a sentence.
    4. NO "SALES" TONE: Do not sound like you are selling the news. Analyze it.
    5. NO GENERIC PHRASES: Do NOT use phrases like "In der heutigen digitalen Welt", "Mit der zunehmenden Digitalisierung".
       -> INSTEAD: Be specific to the news item.
    6. NO APOLOGIES: Do NOT say "As a SOC analyst I see this in my logs" for non-technical news.
       -> INSTEAD: Discuss from a Risk Management (GRC) perspective: Mention "Availability Risks", "Supply Chain", or "Business Continuity".    
    


    CRITICAL INSTRUCTION (THE "HUMAN" RULE):
    - **DO NOT** structure the text with headers like "### Hook" or "### Story". 
    - **DO NOT** use labels like "Analysis:" or "The Good:".
    - **WRITE A FLUID STORY.** One paragraph must flow into the next naturally using transition phrases (e.g., "Das Kranke daran ist...", "Für mich heißt das...").

    CRITICAL VISUAL RULE (CONTEXTUAL EMOJIS):
    - **Analyze the content first.**
    - **Do NOT use headers** (like "### Analysis").
    - **IF the news is about Politics, Physical Hardware (e.g., Starlink seizures), Laws, or Geopolitics:**
       -> Do NOT say "As a SOC analyst I see this in my logs". That makes no sense.
       -> Instead, discuss it from a **Risk Management (GRC)** perspective: Mention "Availability Risks", "Supply Chain", or "Business Continuity".
    - **Instead, start EVERY paragraph with ONE emoji that matches the topic:**
      - If talking about the **Shock/News** -> use 🚨, 🤯, or ⚠️
      - If talking about the **Technical Hack** -> use 💻, ⚙️, or 🔓
      - If talking about **Bad Consequences** -> use 🛑, ❌, or 📉
      - If talking about **Good News/Patch** -> use ✅, 👍, or 🛠️
      - If talking about **SOC/Defense/Splunk** -> use 🛡️, 🔍, or 👁️
      - If asking a **Question** -> use ❓, 🧐, or 💭



    TONE (VIBE):
    - **Lively & Energetic:** Use phrases like "Stellt euch vor", "Leute, das ist krass", "Endlich!".
    - **Simple Language:** Remove complex bureaucracy. Use professional slang (SOC, SIEM, Ransomware).
    - **Local Context:** Highlight Germany/Europe relevance.
    - **Output Language:** GERMAN.
    - **Avoid Repetition:** Do not use the word "Angriff" or "Attacke" more than 3 times. Use synonyms like "Vorfall", "Bedrohung", "Kampagne", "Infiltration".
    - **Vocabulary:** Use precise IT terms (Backdoor, Supply Chain Attack, Repository, Payload).
    
    CRITICAL LANGUAGE RULE:
    - Language: **100% GERMAN** (Business German). No mixed English grammar.
    - Vibe: "Coffee break with colleagues". Professional but human.
    - Not too surprised ("Krass!"). Be analytical ("Bedenklich", "Spannend").
    - DO NOT mix English words like "already", "however", "but" into German sentences.
    - Technical terms (Exploit, Backdoor, SIEM, VS Code) MUST remain in English.

    STRUCTURE (STRICTLY FOLLOW):
    1. Hook: Start with emotion/question.
    2. The Story: Briefly, in 2-3 sentences, what happened.
    3. Transition to analysis (Pros/Cons).
    4. Impact (GRC & SOC): Why is this important? (Risk, Splunk, Logs).
    5. Engagement: **FORCE A NEW PARAGRAPH HERE.** Start this paragraph strictly with ❓. Ask friends' opinions ("Wie seht ihr das?", "Eure Meinung?").
    6. Link: **FORCE A NEW PARAGRAPH HERE.** Write ONLY: "🔗 Quelle: {link}"
    7. Hashtags: **FORCE A NEW PARAGRAPH HERE.** Add 4-5 relevant hashtags on a new line (e.g. #CyberSecurity #SOC).

    VISUAL STRUCTURE (EMOJIS):
    Start paragraphs with these emojis ONLY:
    - 🚨 (News/Alert)
    - ⚙️ (Technical Details/Hack)
    - 🛡️ (Defense/SOC/GRC Perspective)
    - ❓ (Discussion Question)

    FORMATTING RESTRICTIONS (STRICT):
    - NO Markdown headers (###).
    - NO Bold text (**text**). Use "quotation marks".
    - NO Bullet points (*). Use emojis (🛡️, 🚨, 📉, 💻).
    - NO Beer emojis (🍺).

    
    INPUT NEWS:
    Title: "{title}"
    Summary: "{summary}"
    Link: {link}
    """


# 2. Функция очистки текста
def clean_response_text(text):
    text = text.replace("—", "-")
    text = text.replace("`", '"')
    text = text.replace("*", '"')
    text = text.replace('""', '"')
    text = text.replace("###", "")
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


# ==========================================
# ГЕНЕРАТОР ПОСТОВ
# ==========================================
def generate_linkedin_post(title, summary, link):
    logging.info(f"🧠 Генерирую пост: {title[:30]}...")
    prompt_text = create_prompt(title, summary, link)

    # --- ПОПЫТКА 1: GEMINI (Google) ---
    try:
        logging.info(f"🔹 Пробую Gemini ({GEMINI_MODEL})...")
        response = client_gemini.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt_text,
            config={"temperature": 0.3},
        )
        logging.info("✅ Gemini успешно сгенерировал.")
        return clean_response_text(response.text)

    except Exception as e_gemini:
        logging.warning(f"⚠️ Ошибка Gemini: {e_gemini}")

        # --- ПОПЫТКА 2: GROQ (Llama 3 - Бесплатно) ---
        if client_groq:
            logging.info(f"🔄 Переключаюсь на Groq ({GROQ_MODEL})...")
            try:
                chat_completion = client_groq.chat.completions.create(
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a professional LinkedIn ghostwriter.",
                        },
                        {"role": "user", "content": prompt_text},
                    ],
                    model=GROQ_MODEL,
                    temperature=0.3,  # <--- Добавь это. 0.3 делает его строже.
                )
                logging.info("✅ Groq успешно сгенерировал.")
                return clean_response_text(chat_completion.choices[0].message.content)
            except Exception as e_groq:
                return f"❌ Ошибка обоих нейросетей. Groq Error: {e_groq}"
        else:
            return f"❌ Gemini упал, а ключ Groq не задан. Ошибка Gemini: {e_gemini}"


# ==========================================
# ЛОГИКА СКАНЕРА
# ==========================================
def check_news():
    global processed_links

    logging.info("🔎 Сканирую новости...")
    new_post_found = False

    for url in RSS_URLS:
        if new_post_found:
            break

        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                continue

            for entry in feed.entries[:3]:
                # 1. Проверка в памяти
                if entry.link in processed_links:
                    continue

                # 2. Проверка релевантности
                full_text = f"{entry.title} {entry.description}"
                if is_relevant(full_text):
                    logging.info(f"🔥 Нашел релевантную новость: {entry.title}")

                    # 3. Генерация
                    draft = generate_linkedin_post(
                        entry.title, entry.description, entry.link
                    )

                    # 4. Сохранение
                    save_to_history(str(entry.link))
                    processed_links.add(str(entry.link))

                    # 5. ВЫЗЫВАЕМ ГЕНЕРАЦИЮ КАРТИНКИ
                    image_path = generate_image_smart(draft)

                    # 6. ОТПРАВЛЯЕМ В TELEGRAM
                    markup = InlineKeyboardMarkup()
                    markup.add(
                        InlineKeyboardButton( # type: ignore
                            "🚀 Posten", callback_data="post_to_linkedin"
                        )
                    )
                    try:
                        # Если картинка успешно создалась, отправляем сначала её
                        if image_path:
                            with open(image_path, 'rb') as photo:
                                bot.send_photo(chat_id=CHAT_ID, photo=photo)
                            logging.info("✅ Картинка отправлена в Telegram.")

                        # Затем отправляем сам текст поста с кнопкой
                        sent_message = bot.send_message(
                            CHAT_ID,
                            f"📰 {entry.title}\n\n📝 {draft}",
                            reply_markup=markup,
                        )
                        logging.info(f"✅ Черновик отправлен в Telegram. ID: {sent_message.message_id}")

                        # Сохраняем черновик в память, привязав к ID сообщения
                        drafts_in_memory[sent_message.message_id] = draft
                        new_post_found = True
                        break
                    except Exception as e_tg:
                        logging.error(f"❌ Ошибка отправки в Telegram: {e_tg}")
                else:
                    # Если не релевантно - запоминаем, чтобы не проверять снова
                    processed_links.add(str(entry.link))

        except Exception as e:
            logging.error(f"❌ Ошибка при парсинге RSS ({url}): {e}")
            
    if not new_post_found:
        logging.info("✅ Сканирование завершено. Новых релевантных новостей нет.")


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    if call.data == "post_to_linkedin":
        # Извлекаем правильный текст из словаря по ID сообщения
        text_to_post = drafts_in_memory.get(call.message.message_id)
        if not text_to_post:
            bot.answer_callback_query(
                call.id,
                "❌ Ошибка: черновик не найден. Возможно, бот был перезапущен.",
            )
            return
        success = post_to_linkedin(text_to_post)

        if success:
            bot.answer_callback_query(call.id, "✅ Опубликовано в LinkedIn!")
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка при публикации.")


if __name__ == "__main__":
    logging.info(f"📂 Загружено {len(processed_links)} ссылок из history.txt")

    # 1. Сразу при запуске проверяем новости один раз
    check_news()

    # 2. Настраиваем планировщик в отдельном потоке
    def run_scheduler():
        # Рекомендую поставить 60 минут или 2 часа (120)
        schedule.every(120).minutes.do(check_news)
        while True:
            schedule.run_pending()
            time.sleep(1)

    # Запускаем поток с расписанием
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    logging.info("🤖 Бот запущен и готов к работе...")

    # 3. Запускаем бесконечный опрос Telegram
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        logging.critical(f"💥 Критическая ошибка в главном цикле polling: {e}")
        time.sleep(15)  # Пауза перед перезапуском при сбое сети

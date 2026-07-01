import logging
import os
import sys
import threading
import json
import time
import urllib.parse

import feedparser
import requests
import schedule
import telebot
from dotenv import load_dotenv
from groq import Groq  # pip install groq
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# ==========================================
# 🔴 НАСТРОЙКИ (КЛЮЧИ ИЗ .ENV)
# ==========================================
# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

# Загрузка переменных окружения только для локального запуска (когда нет Docker)
# В Docker-контейнере переменные передаются через docker-compose.yml
load_dotenv(".env")

# --- Telegram ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", 0))

# --- API Ключи ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# --- Настройки контента ---
RSS_URLS = [url.strip(' "') for url in os.getenv("RSS_URLS", "").split(",") if url.strip()]
KEYWORDS_INCLUDE = os.getenv("KEYWORDS_INCLUDE", "").split(",")
KEYWORDS_EXCLUDE = os.getenv("KEYWORDS_EXCLUDE", "").split(",")
GROQ_MODEL = "llama-3.3-70b-versatile"

# --- Файл истории ---
DATA_DIR = "/app/data" # Папка для хранения данных в Docker-томе
HISTORY_FILE = os.path.join(DATA_DIR, "history.txt")
CACHE_FILE = os.path.join(DATA_DIR, "news_cache.json")
os.makedirs(DATA_DIR, exist_ok=True) # Создаем папку, если ее нет


# ==========================================
# ПРОВЕРКА КРИТИЧЕСКИХ ПЕРЕМЕННЫХ
# ==========================================
def validate_env_vars():
    """Проверяет наличие всех необходимых переменных окружения."""
    required_vars = {
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "CHAT_ID": CHAT_ID,
        "GROQ_API_KEY": GROQ_API_KEY,
        "RSS_URLS": RSS_URLS and RSS_URLS[0],  # Проверяем, что список не пустой
        "KEYWORDS_INCLUDE": KEYWORDS_INCLUDE and KEYWORDS_INCLUDE[0],  # И здесь тоже
    }
    
    # Логируем статус каждой переменной для отладки
    for key, value in required_vars.items():
        status = "✅" if value else "❌"
        logging.info(f"Проверка переменной: {key} ... {status}")

    missing_vars = [key for key, value in required_vars.items() if not value]
    if missing_vars:
        logging.error(
            f"❌ Критическая ошибка: Отсутствуют переменные в .env: {', '.join(missing_vars)}"
        )
        logging.error("💡 Убедитесь, что в файле .env заданы значения для всех этих ключей и перезапустите контейнер.")
        sys.exit(1)


validate_env_vars()

# ==========================================
# ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ
# ==========================================
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Инициализация Groq
client_groq = None
if GROQ_API_KEY and GROQ_API_KEY.startswith("gsk_"):
    client_groq = Groq(api_key=GROQ_API_KEY)

# Глобальные переменные для хранения состояния
processed_links = set()


# ==========================================
# ЛОГИКА КЭША НОВОСТЕЙ (NEWS_CACHE.JSON)
# ==========================================
def load_news_cache():
    """Загружает кэш новостей из JSON-файла при старте"""
    if os.path.isdir(CACHE_FILE):
        logging.error(
            f"❌ ОШИБКА: '{CACHE_FILE}' является директорией. Удалите ее и перезапустите бота."
        )
        sys.exit(1)

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                # В JSON ключи всегда строки, превращаем ID сообщений обратно в int
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except (json.JSONDecodeError, ValueError) as e:
            logging.error(f"⚠️ Ошибка загрузки или парсинга кэша новостей: {e}. Создается новый кэш.")
            return {}
    else:
        # Если файла нет, создаем его, чтобы избежать создания директории Docker'ом
        open(CACHE_FILE, "a").close()
        logging.info(f"Файл кэша '{CACHE_FILE}' не найден, создан новый пустой файл.")
    return {}


def save_news_cache():
    """Сохраняет текущий кэш новостей в JSON-файл"""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(news_storage, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения кэша новостей на диск: {e}")


# Загружаем кэш из файла при старте скрипта
news_storage = load_news_cache()

# ЛОГИКА ПАМЯТИ (HISTORY.TXT)
# ==========================================


def load_history():
    """Загружает ссылки из файла в память при старте"""
    if os.path.isdir(HISTORY_FILE):
        logging.error(
            f"❌ ОШИБКА: '{HISTORY_FILE}' является директорией. Удалите ее и перезапустите бота."
        )
        sys.exit(1)
    if not os.path.exists(HISTORY_FILE):
        open(HISTORY_FILE, "a").close()
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

def is_relevant(text):
    text_lower = text.lower()
    if any(word.lower() in text_lower for word in KEYWORDS_EXCLUDE if word):
        return None
    for word in KEYWORDS_INCLUDE:
        if word and word.lower() in text_lower:
            return word  # Возвращаем найденное ключевое слово
    return None


# 1. Единый Промпт для всех нейросетей (ИНТЕГРИРОВАН НОВЫЙ ЖИВОЙ ВАРИАНТ)
def create_prompt(title, summary, link, lang="DE"):
    full_content = f"{title} {summary}".lower()

    # Проверяем, относится ли новость к карьере, обучению или акциям
    is_career_or_promo = any(word in full_content for word in [
        "cert", "education", "job", "career", "scholarship", "voucher", "free exam", "mentorship", "training"
    ])

    # Уникальные жесткие инструкции и ИТ-сленг для каждого языка отдельно, включая критические приветствия
    lang_map = {
        "DE": """
        Write 100% in Business German. 
        Tone: Professional, expert, but casual ("Coffee break with colleagues").
        CRITICAL GREETING: Start strictly with "Hallo Community!" or "Hallo Kollegen!". Do NOT use "Hallo ihr".
        CRITICAL: Use ONLY informal "du", "ihr", "euch", "eure". Formal "Sie/Ihre" is STRICTLY FORBIDDEN.
        Do NOT hardcode specific infrastructure terms unless they are explicitly mentioned in the input news. Use flexible German IT terminology tailored strictly to the actual threat vector (e.g., Access Management, Datenvertraulichkeit, Richtlinien).
        """,
        
        "EN": """
        Write 100% in English (US). 
        Tone: High-energy, professional, tech-savvy. 
        Style: Modern LinkedIn tech-influencer/engineer.
        CRITICAL GREETING: Start strictly with "Hi Community," or "Hello colleagues,". Do NOT use "Hey folks" or "Hi guys".
        Use words like: "compromised", "blast radius", "identity security", "least privilege".
        Address the community naturally: "What's your take on this?".
        """,
        
        "UA": """
        Write 100% in Ukrainian. 
        Tone: Professional, modern, peer-to-peer (як інженер для інженерів).
        CRITICAL GREETING: Start strictly with "Вітаю, колеги!" or "Привіт, ком'юніті!". 
        DO NOT copy raw prompt text like "ви/ваша думка".
        Address the audience using respectful "ви / ваш / як ви вважаєте".
        Use natural Ukrainian IT slang combined with English terms: інсайдерські загрози, Privilege Escalation, логування, компрометація облікових записів, мінімальні привілеї (Least Privilege).
        """,
        
        "RU": """
        Write 100% in Russian. 
        Tone: Professional, experts-only, direct.
        Style: Живой блог практикующего инженера. Без канцеляризмов и без панибратства.
        CRITICAL GREETING: Start strictly with "Приветствую, коллеги!" or "Привет, комьюнити!". 
        STRICTLY FORBIDDEN to use words like "ребята", "парни", "мальчики". This is for senior IT professionals.
        Address the audience using professional "вы", "коллеги". 
        Use standard, active SOC-analyst slang: инсайдерские угрозы, эскалация привилегий, Privilege Escalation, собирать логи, SIEM/Splunk, модель нулевого доверия (Zero Trust), учетки.
        """
    }
    
    target_lang_instruction = lang_map.get(lang, lang_map["DE"])

    if is_career_or_promo:
        # ==========================================
        # СТИЛЬ Б: КАРЬЕРА, СЕРТИФИКАЦИИ, ОБУЧЕНИЕ
        # ==========================================
        return f"""
        ROLE:
        You are an experienced SOC Analyst sharing useful career opportunities, initiatives, materials, and free certifications for students and juniors on LinkedIn. 
        Your tone must be empowering, motivating, and supportive.

        CORE REASONING RULE:
        If the input 'Summary' or 'Title' is too short or abstract, use your deep cyber security knowledge base to reconstruct the technical context. Do NOT write tautologies.

        TASK:
        Write a LinkedIn post about a great career opportunity or community initiative based on the input text.

        🚫 NEGATIVE CONSTRAINTS:
        1. DO NOT mention "Business Continuity Risks", "Availability Risks", or "CISOs" for career posts.
        2. DO NOT say you "discovered" or "analyzed" this yourself. You just found this great news/resource.
        3. NO Markdown headers (###), NO Bold text (**text**), NO Bullet points (*).
        4. OUTPUT LANGUAGE: {target_lang_instruction}

        STRUCTURE & VISUAL RULES (STRICTLY FOLLOW):
        1. 👋 **Intro:** Greet the IT community warmly. Mention you found a great resource for career development or certification prep.
        2. 📰 **Original Title:** On a new line, output the original English title with a 📰 emoji.
        3. 🚀 **The Opportunity:** Briefly explain what this resource/initiative is about (2-3 sentences). Start with 🚀.
        4. 💡 **Your Advice / Value:** Provide concrete examples of practical value a junior can get there (e.g., cert names like CompTIA Security+, Cisco CyberOps, or how to pass a CV filter). Start with 💡.
        5. 🎯 **Call to Action:** Encourage the community to use this opportunity ("Nutzt diese Chance" / "Используйте этот шанс" etc.). Start with 🎯.
        6. ❓ **Discussion:** Start a new paragraph strictly with the ❓ emoji followed immediately by the question text on the same line (e.g., "❓ Wie seht ihr..."). DO NOT leave the emoji alone on a line.
        7. 🔗 **Link:** Start a new paragraph. Write exactly: "🔗 Quelle: {link}"
        8. #️⃣ **Hashtags:** Force a new line. Add 4-5 relevant hashtags.

        INPUT NEWS:
        Title: "{title}"
        Summary: "{summary}"
        Link: {link}
        """
    else:
        # ==========================================
        # STYLE A: CYBERATTACKS & VULNERABILITIES
        # ==========================================
        return f"""
        ROLE:
        You are a practicing SOC Analyst running a professional technical blog on LinkedIn for fellow IT professionals, SOC analysts, and system administrators. 
        Your tone is professional, expert, analytical, and CONCISE.

        TASK:
        Analyze the provided cyber security news and write a LinkedIn post. 

        🚫 NEGATIVE CONSTRAINTS:
        1. DO NOT say you "discovered" or "detected" this vulnerability yourself.
        2. DO NOT address only CISOs. Focus on the practicing IT community.
        3. NO TAUTOLOGIES & EMPTY PHRASES: Do not write sentences like "Die Angreifer nutzen Exploits, um Lücken auszunutzen".
        4. NO Markdown headers (###), NO Bold text (**text**), NO Bullet points (*).
        5. OUTPUT LANGUAGE: {target_lang_instruction}

        STRUCTURE & VISUAL RULES (STRICTLY FOLLOW):
        1. 👋 **Intro:** Greet the community and mention a critical alert you just read about.
        2. 📰 **Original Title:** The original English title with a 📰 emoji.
        3. ⚙️ **Technical Details:** Explain exactly WHAT happened based on the source. Mention specific vectors if applicable (e.g., credential leaking, configuration flaws, or access abuse). Max 2-3 packed, high-value sentences. Start strictly with a ⚙️ emoji.
        4. ⚠️ **The Core Threat:** Highlight the exact technical or architectural reason why this is critical (e.g., threat to data confidentiality, system integrity, or stealthy persistence in the network). Be precise and avoid generic noise. Start strictly with a ⚠️ emoji.
        5. 🛡️ **Community Verdict (SOC/GRC):** Provide professional analytical insight instead of generic advice. Mention concrete defense steps relevant to the specific threat type: what should an engineer check tomorrow morning? (e.g., tailored architectural hardening, specific monitoring focus, access control updates, or technical verification metrics). Start strictly with a 🛡️ emoji.
        6. ❓ **Discussion:** Start a new paragraph strictly with the ❓ emoji followed immediately by the question text on the same line (e.g., "❓ Wie seht ihr..."). DO NOT leave the emoji alone on a line.
        7. 🔗 **Link:** Start a new paragraph. Write exactly: "🔗 Quelle: {link}"
        8. #️⃣ **Hashtags:** Force a new line. Add hashtags.

        INPUT NEWS:
        Title: "{title}"
        Summary: "{summary}"
        Link: {link}
        """

# 2. Функция очистки текста
def clean_response_text(text):
    text = text.replace("—", "-").replace("`", '"').replace("*", '"').replace('""', '"').replace("###", "")
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


# ==========================================
# ГЕНЕРАТОР ПОСТОВ
# ==========================================
def generate_linkedin_post(title, summary, link, lang="DE"):
    # --- Используем только GROQ (Llama 3.3) ---
    if not client_groq:
        logging.error("❌ Клиент Groq не инициализирован.")
        return None

    logging.info(f"🧠 Генерирую пост ({lang}): {title[:30]}...")
    prompt_text = create_prompt(title, summary, link, lang)

    try:
        chat_completion = client_groq.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional LinkedIn ghostwriter who follows instructions precisely.",
                },
                {"role": "user", "content": prompt_text},
            ],
            model=GROQ_MODEL,
            temperature=0.4,
        )
        post_text = chat_completion.choices[0].message.content
        return clean_response_text(post_text)
    except Exception as e_groq:
        error_message = str(e_groq)
        logging.error(f"❌ Ошибка Groq: {error_message}")
        if "rate_limit_exceeded" in error_message or "429" in error_message:
            return "RATE_LIMIT_EXCEEDED"
        return None


# ==========================================
# СБОРЩИК КЛАВИАТУРЫ
# ==========================================
def build_keyboard(draft_text, link, current_lang="DE"):
    encoded_text = urllib.parse.quote(draft_text)
    encoded_link = urllib.parse.quote(link)
    linkedin_web_url = f"https://www.linkedin.com/sharing/share-offsite/?url={encoded_link}&text={encoded_text}"
    
    markup = InlineKeyboardMarkup(row_width=4)
    
    # Кнопки выбора языков. Активный язык помечаем галочкой ✅
    btn_de = InlineKeyboardButton(f"{'✅ ' if current_lang=='DE' else ''}DE", callback_data="lang_de")
    btn_en = InlineKeyboardButton(f"{'✅ ' if current_lang=='EN' else ''}EN", callback_data="lang_en")
    btn_ua = InlineKeyboardButton(f"{'✅ ' if current_lang=='UA' else ''}UA", callback_data="lang_ua")
    btn_ru = InlineKeyboardButton(f"{'✅ ' if current_lang=='RU' else ''}RU", callback_data="lang_ru")
    
    markup.add(btn_de, btn_en, btn_ua, btn_ru)
    # Главная кнопка публикации всегда ведет на актуальный текст
    markup.add(InlineKeyboardButton("🚀 Открыть в LinkedIn", url=linkedin_web_url))
    return markup

# ==========================================
# ЛОГИКА СКАНЕРА
# ==========================================
def check_news():
    global processed_links, news_storage
    
    logging.info("🔎 Запуск сквозного сканирования ВСЕХ ресурсов...")
    
    # Проходим абсолютно по каждому URL из списка источников
    for url in RSS_URLS:
        try:
            logging.info(f"Паршу источник: {url}")
            
            # Прикидываемся браузером, чтобы сервера отдавали XML без лишних проверок
            feed = feedparser.parse(url, agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

            if not feed.entries:
                logging.info(f"Источник пуст или недоступен (нет записей): {url}")
                continue
    
            # Берем топ-3 свежих записей из текущего источника
            for entry in feed.entries[:3]:
                # Если ссылку уже обрабатывали ранее — строго пропускаем
                if entry.link in processed_links:
                    continue
    
                full_text = f"{entry.title} {entry.description}"
                relevance_keyword = is_relevant(full_text)
                if relevance_keyword:
                    logging.info(f"🔥 Нашел релевантную новость: {entry.title} ({url})")
    
                    # Изначально генерируем на немецком (DE)
                    draft = generate_linkedin_post(entry.title, entry.description, entry.link, lang="DE")
                    if not draft:
                        continue
    
                    markup = build_keyboard(draft, entry.link, current_lang="DE")
    
                    try:
                        sent_message = bot.send_message(CHAT_ID, draft, reply_markup=markup)
                        logging.info(f"✅ Черновик отправлен. ID: {sent_message.message_id}")
    
                        # Сохраняем метаданные и первый черновик, привязывая к ID сообщения в TG
                        news_storage[sent_message.message_id] = {
                            "title": entry.title,
                            "description": entry.description,
                            "link": entry.link,
                            "drafts": {"DE": draft},  # Сохраняем первый сгенерированный черновик
                        }
                        # Сразу фиксируем изменения на диске
                        save_news_cache()
                        
                        save_to_history(str(entry.link))
                        processed_links.add(str(entry.link))

                    except Exception as e_tg:
                        logging.error(f"❌ Ошибка отправки в Telegram: {e_tg}")
                else:
                    processed_links.add(str(entry.link))

        except Exception as e:
            logging.error(f"❌ Ошибка при парсинге RSS ({url}): {e}")


# ==========================================
# ОБРАБОТЧИК ИНТЕРАКТИВНЫХ КНОПОК ЯЗЫКА
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("lang_"))
def handle_language_switch(call):
    message_id = call.message.message_id
    target_lang = call.data.split("_")[1].upper() # Получаем DE, EN, UA или RU
    
    # Достаем сохраненный оригинал новости
    news_data = news_storage.get(message_id)
    if not news_data:
        bot.answer_callback_query(call.id, "❌ Ошибка: Исходные данные новости не найдены в памяти.")
        return

    # 1. Проверяем, есть ли уже готовый черновик в кэше
    if target_lang in news_data.get("drafts", {}):
        new_draft = news_data["drafts"][target_lang]
        bot.answer_callback_query(call.id, f"✅ Загружено из кэша: {target_lang}")
    else:
        # 2. Если в кэше нет, генерируем и сохраняем
        bot.answer_callback_query(call.id, f"🔄 Генерирую пост на языке: {target_lang}...")
        new_draft = generate_linkedin_post(news_data["title"], news_data["description"], news_data["link"], lang=target_lang)
        if new_draft and new_draft != "RATE_LIMIT_EXCEEDED":
            news_storage[message_id]["drafts"][target_lang] = new_draft
            # Сохраняем обновленный кэш с новым переводом
            save_news_cache()
    
    if new_draft:
        # Пересобираем клавиатуру с новым текстом внутри ссылки LinkedIn и ставим галочку на нужный язык
        new_markup = build_keyboard(new_draft, news_data["link"], current_lang=target_lang)
        
        # Обновляем сообщение в Telegram на лету!
        bot.edit_message_text(chat_id=CHAT_ID, message_id=message_id, text=new_draft, reply_markup=new_markup)
    else:
        error_text = "❌ Ошибка генерации текста."
        if new_draft == "RATE_LIMIT_EXCEEDED":
            error_text = "🚫 API-лимит исчерпан. Попробуйте позже."
        bot.answer_callback_query(call.id, error_text)


if __name__ == "__main__":
    logging.info(f"📂 Загружено {len(processed_links)} ссылок из history.txt")

    check_news()

    def run_scheduler():
        schedule.every(120).minutes.do(check_news)
        while True:
            schedule.run_pending()
            time.sleep(1)

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    logging.info("🤖 Бот запущен и готов к работе...")

    try:
        bot.polling(none_stop=True)
    except Exception as e:
        logging.critical(f"💥 Критическая ошибка в polling: {e}")
        time.sleep(15)

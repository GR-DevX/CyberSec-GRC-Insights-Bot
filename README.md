# 🛡️ CyberSec GRC Insights Bot

An automated intelligence pipeline designed for **SOC Analysts** and **GRC Professionals**. This bot monitors global cybersecurity RSS feeds, analyzes threats using LLMs, and generates professional LinkedIn content with a human touch.

## 🚀 Key Features

- **Smart RSS Monitoring**: Automated scanning of top-tier security sources like Heise Security, The Hacker News, and BSI Bund.
- **GRC-Focused Analysis**: Specifically filters for Ransomware, Supply Chain risks, and Data Breaches while ignoring noise (e.g., Crypto/Bitcoin).
- **AI Fallback System**: High availability ensured by a dual-model architecture. If Google **Gemini 1.5 Flash** reaches rate limits, the system automatically switches to **Groq (Llama 3)**.
- **Persistent History**: Uses a local `history.txt` database to ensure no news item is ever processed or posted twice.
- **Interactive Review**: Integrated Telegram interface for manual validation before final publishing to LinkedIn.

## 🛠 Tech Stack

- **Language**: Python 3.10+
- **AI Engines**: Google Generative AI & Groq Cloud API.
- **Communication**: pyTelegramBotAPI (Telebot).
- **Data Handling**: Feedparser & Schedule.
- **Security**: Dotenv for environment variable protection.

## 📋 How It Works (The Pipeline)

1. **Ingestion**: Scans defined RSS feeds for new entries.
2. **Filtering**: Validates relevance based on strict GRC/SOC keyword inclusion and exclusion lists.
3. **Synthesis**: Sends technical summaries to AI with a custom "Pub Storytelling" prompt to generate engaging German content.
4. **Formatting**: Cleans AI output to match professional LinkedIn standards (no markdown headers, contextual emojis only).
5. **Validation**: Sends a draft to a private Telegram chat for the owner's approval.
6. **Persistence**: Logs the link to prevent duplicates.

## ⚙️ Installation & Setup

1. **Clone the repository**:

```bash
git clone https://github.com/YourUsername/CyberSec-Insights-Bot.git
cd CyberSec-Insights-Bot

```

2. **Install dependencies**:

```bash
pip install -r requirements.txt

```

3. **Configure Environment Variables**:
   Create a `.env` file in the root directory (refer to `.env.example`):

```env
TELEGRAM_TOKEN=your_tg_token
GEMINI_API_KEY=your_google_key
GROQ_API_KEY=your_groq_key
LINKEDIN_ACCESS_TOKEN=your_linkedin_token

```

## 👤 Author

**Roman Goncharov**

- Master's Student & Junior SOC Analyst
- [LinkedIn Profile](https://www.linkedin.com/in/roman-goncharov-grc/)

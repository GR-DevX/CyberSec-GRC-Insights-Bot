import requests

# 1. ВСТАВЬТЕ ВАШИ ДАННЫЕ ИЗ LINKEDIN DEVELOPERS (раздел Auth)
CLIENT_ID = ""
CLIENT_SECRET = ""
REDIRECT_URI = "https://www.google.com/"

print("1. Откройте эту ссылку в браузере и нажмите 'Allow':")
auth_url = f"https://www.linkedin.com/oauth/v2/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope=openid%20profile%20w_member_social%20email"
print(f"\n{auth_url}\n")

# 2. Получаем ссылку с кодом от пользователя
full_url = input(
    "2. Вас перекинуло на Google. Скопируйте ВСЮ ссылку из адресной строки и вставьте сюда: "
)

# Извлекаем код из ссылки
try:
    auth_code = full_url.split("code=")[1].split("&")[0]
except:
    print("❌ Ошибка: Не удалось найти код в ссылке. Попробуйте еще раз.")
    exit()

# 3. Прямой запрос токена без лишних библиотек
data = {
    "grant_type": "authorization_code",
    "code": auth_code,
    "redirect_uri": REDIRECT_URI,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
}

response = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data=data)

if response.status_code == 200:
    token = response.json().get("access_token")
    print(f"\n✅ ВАШ ТОКЕН ПОЛУЧЕН:\n\n{token}\n")
    print("Скопируйте его в файл .env как LINKEDIN_ACCESS_TOKEN")
else:
    print(f"❌ Ошибка API: {response.text}")

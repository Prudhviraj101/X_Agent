import urllib.request
import json
import os
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

if not token or not chat_id:
    print("Error: Missing credentials in .env")
    exit(1)

url = f"https://api.telegram.org/bot{token}/sendMessage"
data = json.dumps({
    "chat_id": chat_id,
    "text": "🤖 Test message from X Agent: Bot is working!"
}).encode("utf-8")

req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req) as resp:
        print(f"Success: {resp.status}")
        print(resp.read().decode())
except Exception as e:
    print(f"Failed: {e}")

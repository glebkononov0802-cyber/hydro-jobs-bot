"""
telegram_notify.py

Отправка коротких сообщений в Telegram — тот же принцип,
что в finance-bot: коротко, без стены текста.
"""

import os
import requests

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def send_job(job: dict, score: int) -> bool:
    """
    Возвращает True, если Telegram подтвердил доставку.
    Печатает подробности в лог, если что-то пошло не так —
    чтобы GitHub Actions не молчал при ошибке.
    """
    text = (
        f"🟢 HYDRO JOB (+{score})\n\n"
        f"{job['title']}\n"
        f"🏢 Источник: {job['source'].upper()}\n\n"
        f"🔗 {job['url']}"
    )
    resp = requests.post(
        API_URL,
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=15,
    )

    result = resp.json()
    if not result.get("ok"):
        print(f"[TELEGRAM ERROR] {result}")
        return False
    return True

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


def send_job(job: dict, score: int) -> None:
    text = (
        f"🟢 HYDRO JOB (+{score})\n\n"
        f"{job['title']}\n"
        f"🏢 Источник: {job['source'].upper()}\n\n"
        f"🔗 {job['url']}"
    )
    requests.post(
        API_URL,
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=15,
    )

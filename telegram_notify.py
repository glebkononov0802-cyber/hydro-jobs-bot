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


def build_message(job: dict, score: int, details: dict) -> str:
    lines = [f"🟢 HYDRO JOB (+{score})", "", job["title"], f"🏢 {job['source'].upper()}"]

    if details.get("Company"):
        lines.append(f"🏗 {details['Company']}")

    top_line = []
    if details.get("Location"):
        top_line.append(f"📍 {details['Location']}")
    if details.get("Work Type"):
        top_line.append(f"📄 {details['Work Type']}")
    if details.get("Project Type"):
        top_line.append(f"📄 {details['Project Type']}")
    if details.get("Salary"):
        top_line.append(f"💰 {details['Salary']}")
    if top_line:
        lines.append(" · ".join(top_line))

    date_line = []
    if details.get("Start Date"):
        date_line.append(f"📅 {details['Start Date']}")
    if details.get("Posted"):
        date_line.append(f"🗓 Posted: {details['Posted']}")
    if details.get("Duration"):
        date_line.append(details["Duration"])
    if date_line:
        lines.append(" · ".join(date_line))

    if details.get("Software"):
        lines.append(f"🛠 {details['Software']}")

    if details.get("Experience"):
        lines.append(f"🎓 {details['Experience']}")

    if details.get("Positions"):
        lines.append(f"👥 {details['Positions']}")

    if details.get("Scope"):
        lines.append(f"🎯 {details['Scope']}")

    if details.get("Contact Details"):
        lines.append(f"✉️ {details['Contact Details']}")
    if details.get("Contact Phone"):
        lines.append(f"📞 {details['Contact Phone']}")

    description = details.get("description", "").strip()
    if description:
        limit = details.get("description_limit", 220)
        if len(description) > limit:
            description = description[:limit].rstrip() + "…"
        lines.append("")
        lines.append(description)

    lines.append("")
    lines.append(f"🔗 {job['url']}")

    return "\n".join(lines)


def send_alert(text: str) -> bool:
    """
    Отправляет служебное сообщение (не про конкретную вакансию) —
    например, предупреждение, что источник перестал отвечать.
    """
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


def send_job(job: dict, score: int, details: dict | None = None) -> bool:
    """
    Возвращает True, если Telegram подтвердил доставку.
    details — необязательный словарь с Location/Work Type/Start Date/
    Duration/Software/description (см. sources/utm.py fetch_job_details).
    """
    text = build_message(job, score, details or {})
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

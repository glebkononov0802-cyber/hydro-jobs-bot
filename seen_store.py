"""
seen_store.py

Хранит список уже отправленных в Telegram вакансий (по URL),
чтобы не дублировать. Аналог data.json в finance-bot, только
здесь это множество ссылок, а не курсы валют.
"""

import json
import os

DATA_FILE = "seen_jobs.json"


def load_seen() -> set:
    if not os.path.exists(DATA_FILE):
        return set()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_seen(seen: set) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)

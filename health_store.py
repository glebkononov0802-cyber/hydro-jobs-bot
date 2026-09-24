"""
health_store.py

Отслеживает состояние каждого источника (сайта) между запусками бота:
сколько раз подряд не удалось получить данные, и отправляли ли уже
алерт в Telegram про текущую серию сбоев. Нужно, чтобы отличать
"на сайте правда сейчас нет новых вакансий" от "сайт сломался или
заблокировал бота, вакансии оттуда сейчас не видны вообще".
"""

import json
import os

DATA_FILE = "source_health.json"


def load_health() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_health(health: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)

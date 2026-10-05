"""
stats_store.py

Статистика для еженедельного отчёта "Бот жив":
- сколько вакансий реально отправлено за последние 7 дней (всего и по источникам);
- когда последний раз отправляли отчёт.

Хранится в bot_stats.json (коммитится workflow так же, как seen_jobs.json).
"""

from __future__ import annotations
import json
import os
from datetime import datetime, timedelta, timezone

DATA_FILE = "bot_stats.json"
REPORT_EVERY = timedelta(days=7)
KEEP_LOG_FOR = timedelta(days=14)


def load_stats() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def save_stats(stats: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def record_sent(stats: dict, source: str, now: datetime | None = None) -> None:
    """Запоминает, что вакансия от источника source реально ушла в Telegram."""
    now = now or datetime.now(timezone.utc)
    log = stats.setdefault("sent", [])
    log.append({"t": now.isoformat(timespec="seconds"), "src": source})

    # чистим записи старше двух недель, чтобы файл не рос бесконечно
    cutoff = now - KEEP_LOG_FOR
    stats["sent"] = [e for e in log if (_parse(e.get("t")) or now) >= cutoff]


def weekly_counts(stats: dict, now: datetime | None = None) -> tuple[int, dict]:
    """(всего за 7 дней, {источник: сколько})"""
    now = now or datetime.now(timezone.utc)
    cutoff = now - REPORT_EVERY
    per_source: dict[str, int] = {}
    total = 0
    for e in stats.get("sent", []):
        t = _parse(e.get("t"))
        if t and t >= cutoff:
            per_source[e["src"]] = per_source.get(e["src"], 0) + 1
            total += 1
    return total, per_source


def report_due(stats: dict, now: datetime | None = None, force: bool = False) -> bool:
    """
    Пора ли слать отчёт. При самом первом запуске отчёт НЕ шлём — просто
    запоминаем момент старта, чтобы первый отчёт пришёл через неделю.
    """
    now = now or datetime.now(timezone.utc)
    if force:
        return True
    last = _parse(stats.get("last_report"))
    if last is None:
        stats["last_report"] = now.isoformat(timespec="seconds")
        return False
    return now - last >= REPORT_EVERY


def build_report(total: int, per_source: dict, health: dict, labels: dict) -> str:
    """
    Короткий отчёт:
      🤖 Бот жив — отчёт за неделю
      📬 Новых вакансий: 5

      🟢 UTM Consultants — 3
      🟢 AGR
      🔴 SA World — не отвечает
    """
    lines = ["🤖 Бот жив — отчёт за неделю", f"📬 Новых вакансий: {total}", ""]
    for key, label in labels.items():
        failures = health.get(key, {}).get("consecutive_failures", 0)
        count = per_source.get(key, 0)
        if failures > 0:
            lines.append(f"🔴 {label} — не отвечает")
        elif count > 0:
            lines.append(f"🟢 {label} — {count}")
        else:
            lines.append(f"🟢 {label}")
    return "\n".join(lines)

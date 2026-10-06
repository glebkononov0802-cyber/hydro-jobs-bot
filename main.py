"""
main.py — точка входа Hydro Jobs Bot.

Логика:
1. По очереди опрашиваем все источники. Если источник упал с ошибкой
   (сайт недоступен, заблокировал бота, поменял структуру страницы) —
   не роняем весь бот, а запоминаем это через health_store.py.
2. Если источник падает 2 раза подряд — шлём в Telegram одно
   предупреждение (не при каждом падении, чтобы не спамить).
   Как только источник снова заработает — шлём "снова работает".
3. Из того, что удалось собрать, — обычная схема: keyword-фильтр,
   дедупликация, отправка новых релевантных вакансий.
"""

import json
import os
from datetime import datetime, timezone

from job_filter import filter_jobs, ScoredJob
from seen_store import load_seen, save_seen
from health_store import load_health, save_health
from stats_store import (
    load_stats, save_stats, record_sent, weekly_counts, report_due, build_report,
)
from telegram_notify import send_job, send_alert
from sources import utm, agr, oceancrew, insight, etpm, precise, elevate, atlas, css_ship, wrs, sa_world, gerecruit, cmsourcing, hydroeg, ips

# Название источника -> (функция получения списка вакансий, человекочитаемое имя)
SOURCES = {
    "utm": (utm.fetch_jobs, "UTM Consultants"),
    "agr": (agr.fetch_jobs, "AGR"),
    "oceancrew": (oceancrew.fetch_jobs, "OceanCrew"),
    "insight": (insight.fetch_jobs, "Insight Overseas"),
    "etpm": (etpm.fetch_jobs, "ETPM"),
    "precise": (precise.fetch_jobs, "Precise Consultants"),
    "elevate": (elevate.fetch_jobs, "Elevate Offshore"),
    "atlas": (atlas.fetch_jobs, "Atlas NextWave"),
    "css": (css_ship.fetch_jobs, "CSS Ship Services"),
    "wrs": (wrs.fetch_jobs, "WRS (Worldwide Recruitment Solutions)"),
    "sa": (sa_world.fetch_jobs, "SA World"),
    "gerecruit": (gerecruit.fetch_jobs, "gerecruit"),
    "cmsourcing": (cmsourcing.fetch_jobs, "CMSourcing"),
    "hydroeg": (hydroeg.fetch_jobs, "Hydro Energy Group"),
    "ips": (ips.fetch_jobs, "iPS Powerful People"),
}

# Для каждого источника — функция, которая по URL вакансии достаёт
# подробности (Location, Duration и т.п.). Если источника нет в этом
# словаре — сообщение уйдёт без доп. полей, просто заголовок+ссылка.
DETAIL_FETCHERS = {
    "utm": utm.fetch_job_details,
    "agr": agr.fetch_job_details,
    "oceancrew": oceancrew.fetch_job_details,
    "insight": insight.fetch_job_details,
    "etpm": etpm.fetch_job_details,
    "precise": precise.fetch_job_details,
    "elevate": elevate.fetch_job_details,
    "atlas": atlas.fetch_job_details,
    "css": css_ship.fetch_job_details,
    "wrs": wrs.fetch_job_details,
    "sa": sa_world.fetch_job_details,
    "gerecruit": gerecruit.fetch_job_details,
    "cmsourcing": cmsourcing.fetch_job_details,
    "hydroeg": hydroeg.fetch_job_details,
    "ips": ips.fetch_job_details,
}

# Алерт шлём только после стольки неудачных попыток подряд —
# при cron раз в 3 часа это примерно 6 часов реальной проблемы,
# а не разовый временный сбой сайта.
FAILURE_THRESHOLD = 2


def fetch_all_jobs() -> list[dict]:
    health = load_health()
    all_jobs: list[dict] = []

    for name, (fetch_fn, label) in SOURCES.items():
        state = health.get(name, {"consecutive_failures": 0, "alerted": False})

        try:
            jobs = fetch_fn()
            all_jobs.extend(jobs)

            if state["consecutive_failures"] > 0:
                print(f"[HEALTH] {name}: снова работает после {state['consecutive_failures']} неудачных попыток")
                if state.get("alerted"):
                    send_alert(f"✅ {label} снова отвечает — вакансии оттуда снова отслеживаются.")

            state["consecutive_failures"] = 0
            state["alerted"] = False

        except Exception as e:
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            print(f"[HEALTH] {name}: ошибка ({state['consecutive_failures']} подряд): {e}")

            if state["consecutive_failures"] >= FAILURE_THRESHOLD and not state.get("alerted"):
                send_alert(
                    f"⚠️ {label} не отвечает уже {state['consecutive_failures']} проверки подряд.\n\n"
                    f"Ошибка: {e}\n\n"
                    f"Похоже, сайт изменил структуру, временно недоступен или заблокировал бота — "
                    f"вакансии оттуда сейчас НЕ отслеживаются. Это не значит, что там нет вакансий, "
                    f"просто бот их сейчас не видит."
                )
                state["alerted"] = True

        health[name] = state

    save_health(health)
    return all_jobs


def send_weekly_report_if_due(stats: dict) -> None:
    """
    Раз в неделю шлёт короткое "Бот жив": сколько вакансий пришло и какие
    источники работают (🟢) / не работают (🔴). Принудительно — через
    FORCE_REPORT=true (в GitHub: Run workflow -> галочка send_report).
    """
    now = datetime.now(timezone.utc)
    force = os.environ.get("FORCE_REPORT", "").strip().lower() == "true"
    if not report_due(stats, now, force):
        return

    total, per_source = weekly_counts(stats, now)
    labels = {name: label for name, (_, label) in SOURCES.items()}
    text = build_report(total, per_source, load_health(), labels)

    if send_alert(text):
        stats["last_report"] = now.isoformat(timespec="seconds")
        print(f"[REPORT] Недельный отчёт отправлен (вакансий за неделю: {total})")
    else:
        print("[REPORT] Не удалось отправить недельный отчёт — попробую при следующем запуске")


def main():
    all_jobs = fetch_all_jobs()

    scored = filter_jobs(all_jobs)  # уже отсортировано по score, только релевантные

    # Записи с флагом force (например "сырой" режим gerecruit) идут мимо
    # keyword-фильтра — их нужно увидеть в любом случае
    already = {j.url for j in scored}
    for j in all_jobs:
        if j.get("force") and j["url"] not in already:
            scored.append(ScoredJob(title=j["title"], url=j["url"], score=0, source=j.get("source", "")))

    seen = load_seen()
    new_jobs = [j for j in scored if j.url not in seen]

    stats = load_stats()
    stats_before = json.dumps(stats, sort_keys=True)

    sent_count = 0
    for job in new_jobs:
        details = {}
        fetch_details = DETAIL_FETCHERS.get(job.source)
        if fetch_details:
            try:
                details = fetch_details(job.url)
            except Exception as e:
                print(f"[WARN] Не удалось получить детали {job.url}: {e}")

        display_url = details.get("display_url", job.url)

        ok = send_job(
            {"title": job.title, "url": display_url, "source": job.source},
            job.score,
            details,
        )
        if ok:
            seen.add(job.url)
            sent_count += 1
            if not details.get("raw_mode"):
                record_sent(stats, job.source)
        # если Telegram вернул ошибку — НЕ добавляем в seen,
        # чтобы бот попробовал отправить эту же вакансию в следующий раз

    save_seen(seen)

    send_weekly_report_if_due(stats)
    if json.dumps(stats, sort_keys=True) != stats_before:
        save_stats(stats)

    print(
        f"Всего найдено: {len(all_jobs)} | "
        f"релевантных: {len(scored)} | "
        f"реально отправлено: {sent_count} из {len(new_jobs)}"
    )


if __name__ == "__main__":
    main()

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

from job_filter import filter_jobs
from seen_store import load_seen, save_seen
from health_store import load_health, save_health
from telegram_notify import send_job, send_alert
from sources import utm, agr, oceancrew, insight, etpm, precise, elevate, atlas

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


def main():
    all_jobs = fetch_all_jobs()

    scored = filter_jobs(all_jobs)  # уже отсортировано по score, только релевантные

    seen = load_seen()
    new_jobs = [j for j in scored if j.url not in seen]

    sent_count = 0
    for job in new_jobs:
        details = {}
        fetch_details = DETAIL_FETCHERS.get(job.source)
        if fetch_details:
            try:
                details = fetch_details(job.url)
            except Exception as e:
                print(f"[WARN] Не удалось получить детали {job.url}: {e}")

        ok = send_job(
            {"title": job.title, "url": job.url, "source": job.source},
            job.score,
            details,
        )
        if ok:
            seen.add(job.url)
            sent_count += 1
        # если Telegram вернул ошибку — НЕ добавляем в seen,
        # чтобы бот попробовал отправить эту же вакансию в следующий раз

    save_seen(seen)

    print(
        f"Всего найдено: {len(all_jobs)} | "
        f"релевантных: {len(scored)} | "
        f"реально отправлено: {sent_count} из {len(new_jobs)}"
    )


if __name__ == "__main__":
    main()

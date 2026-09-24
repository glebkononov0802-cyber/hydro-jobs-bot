"""
main.py — точка входа Hydro Jobs Bot.

Логика (та же, что в finance-bot, только вместо курсов — вакансии):
1. Собираем вакансии из всех источников (пока — только UTM).
2. Прогоняем через keyword-фильтр (job_filter.py).
3. Убираем уже виденные (seen_store.py).
4. Новые релевантные — отправляем в Telegram.
5. Обновляем список виденных.
"""

from job_filter import filter_jobs
from seen_store import load_seen, save_seen
from telegram_notify import send_job
from sources import utm, agr

# Для каждого источника — функция, которая по URL вакансии достаёт
# подробности (Location, Duration и т.п.). Если источника нет в этом
# словаре — сообщение уйдёт без доп. полей, просто заголовок+ссылка.
DETAIL_FETCHERS = {
    "utm": utm.fetch_job_details,
    "agr": agr.fetch_job_details,
}


def main():
    all_jobs = []
    all_jobs.extend(utm.fetch_jobs())
    all_jobs.extend(agr.fetch_jobs())
    # сюда позже добавятся другие источники:
    # all_jobs.extend(oceancrew.fetch_jobs())

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

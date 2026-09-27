"""
sources/precise.py

Парсер вакансий с сайта Precise Consultants (preciseconsultants.com).
Сайт построен на платформе Applyflow — вакансии полностью грузятся
через JS, но сам виджет обращается к открытому JSON API:

    https://account-api-uk.applyflow.com/api/seeker/v1/search-job

Это общий API для множества сайтов на Applyflow, поэтому важно
отправлять правильные "tenant"-заголовки (Site-Code, Job-Buckets и т.д.),
иначе API не поймёт, чей это запрос.

Структура ответа проверена вживую по логам первого реального запуска:
вакансии лежат в data["search_results"]["jobs"], у каждой вакансии
есть job_title, job_description, URL, location_label, consultant_email,
pay_description и т.д.
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

API_URL = "https://account-api-uk.applyflow.com/api/seeker/v1/search-job"
BASE_URL = "https://www.preciseconsultants.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)",
    "Referer": "https://www.preciseconsultants.com/jobs/",
    "Origin": "https://www.preciseconsultants.com",
    "Accept": "application/json",
    "Platform-Code": "applyflow",
    "Site-Code": "precise-consultants",
    "Job-Buckets": "PRECISE-CONSULTANTS",
    "Seeker-Buckets": "precise-consultants",
}


def _strip_html(text: str) -> str:
    """job_description иногда приходит с HTML-разметкой — снимаем её."""
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)


def _absolute_url(url: str) -> str:
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return BASE_URL + "/" + url.lstrip("/")


def _build_job_entry(item: dict) -> dict | None:
    title = item.get("job_title") or ""
    # apply_url обычно рабочая обычная ссылка (не завязана на JS-роутинг
    # сайта), а поле URL иногда оказывается внутренним SPA-маршрутом,
    # который отдаёт 404 при прямом переходе — поэтому предпочитаем apply_url
    url = item.get("apply_url") or item.get("URL") or ""
    if not title or not url:
        return None

    url = _absolute_url(url)

    location = item.get("location_label") or ""
    body = _strip_html(item.get("job_description") or item.get("short_description") or item.get("job_body") or "")

    description = f"{location}. {body}".strip(". ").strip()

    return {
        "title": title,
        "url": url,
        "description": description,
        "source": "precise",
    }


def _fetch_page(page: int) -> list[dict] | None:
    """Возвращает список вакансий (сырых JSON-объектов) со страницы API,
    или None если что-то пошло не так (уже залогировано)."""
    params = {"url": "/", "facet": 1, "allow_backfill": "true", "page": page}

    resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=20)
    print(f"[DEBUG] Precise страница {page}: HTTP статус {resp.status_code}")

    if resp.status_code != 200:
        print(f"[DEBUG] Precise: тело ответа при ошибке: {resp.text[:300]}")
        return None

    try:
        data = resp.json()
    except ValueError:
        print("[DEBUG] Precise: ответ не является JSON")
        return None

    search_results = data.get("search_results") if isinstance(data, dict) else None
    if not isinstance(search_results, dict):
        print("[DEBUG] Precise: search_results отсутствует или не словарь")
        return None

    job_list = search_results.get("jobs")
    if not isinstance(job_list, list):
        print("[DEBUG] Precise: search_results.jobs отсутствует или не список")
        return None

    return job_list


def fetch_jobs(max_pages: int = 2) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "precise"}
    """
    jobs: list[dict] = []

    for page in range(1, max_pages + 1):
        job_list = _fetch_page(page)
        if job_list is None:
            break

        print(f"[DEBUG] Precise: вакансий на странице {page}: {len(job_list)}")

        if page == 1 and job_list:
            import json as _json
            print("[DEBUG] Precise: полный JSON первой вакансии для сверки полей:")
            print(_json.dumps(job_list[0], ensure_ascii=False, indent=2)[:4000])

        if not job_list:
            break

        for item in job_list:
            if not isinstance(item, dict):
                continue
            entry = _build_job_entry(item)
            if entry:
                jobs.append(entry)

    print(f"[DEBUG] Precise: всего вакансий собрано: {len(jobs)}")
    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Страница вакансии — часть SPA и не открывается напрямую снаружи
    (подтверждено на практике), поэтому все детали достаём из того же
    API, что и список. Кастомные поля сайта (Role/Project Type/Software/
    Duration/... — точные названия видны в логе через полный JSON-дамп
    в fetch_jobs) добавляются автоматически под своими же названиями.
    """
    details: dict = {}

    for page in range(1, 3):
        job_list = _fetch_page(page)
        if not job_list:
            break

        found_item = None
        for item in job_list:
            if not isinstance(item, dict):
                continue
            item_url = _absolute_url(item.get("apply_url") or item.get("URL") or "")
            if item_url == url:
                found_item = item
                break

        if found_item:
            item = found_item

            if item.get("location_label"):
                details["Location"] = item["location_label"]

            body = _strip_html(
                item.get("job_description") or item.get("short_description") or item.get("job_body") or ""
            )
            if body:
                details["description"] = body

            # Контакт: имя + телефон одной строкой, email следующей
            name = item.get("consultant_name")
            phone = item.get("consultant_detail")
            email = item.get("consultant_email") or item.get("apply_email")
            contact_lines = []
            first_line = " ".join(str(p) for p in (name, phone) if p)
            if first_line:
                contact_lines.append(first_line)
            if email:
                contact_lines.append(str(email))
            if contact_lines:
                details["Contact Details"] = "\n".join(contact_lines)

            # Кастомные поля сайта (лейбл берём прямо из данных, а не гадаем)
            for i in range(1, 5):
                label = item.get(f"applyflow_custom_{i}")
                value = item.get(f"custom_detail_{i}")
                if label and value:
                    details[str(label)] = str(value)

            ref = item.get("source_reference") or item.get("advertiser_reference")
            if ref:
                details["Reference"] = str(ref)

            pay = item.get("pay_description")
            if pay:
                details["Salary"] = pay

            break

    # Прямые ссылки на конкретную вакансию у Precise не открываются
    # снаружи (SPA без серверных маршрутов) — даём рабочую ссылку на
    # общий список вакансий вместо битой, название уже есть в сообщении
    details["display_url"] = "https://www.preciseconsultants.com/jobs/"

    return details


if __name__ == "__main__":
    found = fetch_jobs()
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found[:10]:
        print("-", j["title"], "->", j["url"])
        print("  ", j["description"][:200])

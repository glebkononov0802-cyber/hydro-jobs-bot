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
    Страница вакансии — часть SPA и не открывается напрямую снаружи,
    поэтому все детали достаём из API. job_body содержит HTML с теми же
    подписанными полями (Role/Project Type/Start Date/Duration/Software/
    Requirements/Location), что видно на самом сайте — разбираем их по
    тегам <strong>.
    """
    details: dict = {}

    label_map = {
        "project type": "Project Type",
        "start date": "Start Date",
        "duration": "Duration",
        "software": "Software",
        "requirements": "Requirements",
        "location": "Location",
        # "role" сознательно пропускаем — дублирует заголовок вакансии
    }

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

            if item.get("short_description"):
                details["description"] = item["short_description"]

            # job_body — HTML с подписанными полями через <strong>Label</strong>
            job_body_html = item.get("job_body") or ""
            if job_body_html:
                body_soup = BeautifulSoup(job_body_html, "html.parser")
                for p in body_soup.find_all("p"):
                    strong = p.find("strong")
                    if not strong:
                        continue
                    label_raw = strong.get_text(strip=True).rstrip(":").strip().lower()
                    target_key = label_map.get(label_raw)
                    if not target_key:
                        continue
                    full_p_text = p.get_text(" ", strip=True)
                    value = full_p_text[len(strong.get_text(strip=True)):].strip()
                    if value:
                        details[target_key] = value

            # Контакт: имя + телефон одной строкой, email следующей —
            # реальный телефон лежит внутри вложенного consultant_detail
            name = item.get("consultant_name")
            consultant_detail = item.get("consultant_detail")
            phone = consultant_detail.get("phone") if isinstance(consultant_detail, dict) else None
            email = item.get("consultant_email") or item.get("apply_email")

            contact_lines = []
            first_line = " ".join(str(p) for p in (name, phone) if p)
            if first_line:
                contact_lines.append(first_line)
            if email:
                contact_lines.append(str(email))
            if contact_lines:
                details["Contact Details"] = "\n".join(contact_lines)

            # Тип занятости (Contract/Permanent) — первое кастомное поле;
            # приходит как список с одним объектом, а не просто строкой
            custom_1 = item.get("custom_detail_1")
            if isinstance(custom_1, list) and custom_1 and isinstance(custom_1[0], dict):
                work_type = custom_1[0].get("value")
                if work_type:
                    details["Work Type"] = work_type

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

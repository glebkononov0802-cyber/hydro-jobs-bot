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
    url = item.get("URL") or item.get("apply_url") or ""
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
    Открывает страницу конкретной вакансии (не API) и вытаскивает
    Role/Project Type/Start Date/Duration/Software/Requirements/Location
    плюс контакт консультанта (имя, телефон, email).

    Структура страницы не проверена вживую (сайт недоступен для прямого
    фетча из среды разработки) — пробуем и табличный, и текстовый разбор,
    с запасным вариантом через API, если разметка страницы не совпадёт
    с ожидаемой.
    """
    details: dict = {}

    try:
        resp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=20)
        resp.encoding = "utf-8"
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            full_text = soup.get_text(" ", strip=True)

            known_labels = ["Role", "Project Type", "Start Date", "Duration", "Software", "Requirements", "Location", "Consultant"]
            label_pattern = r"(" + "|".join(re.escape(l) for l in known_labels) + r")\s*:?\s*"
            matches = list(re.finditer(label_pattern, full_text))
            for i, m in enumerate(matches):
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else start + 120
                value = full_text[start:end].strip()
                if value:
                    details[m.group(1)] = value

            # Консультант: имя обычно сразу после слова "Consultant",
            # телефон и email — из ссылок tel:/mailto:
            consultant_match = re.search(r"Consultant\s*([A-Z][a-zA-Z .'-]+)", full_text)
            phone_link = soup.find("a", href=re.compile(r"^tel:"))
            email_link = soup.find("a", href=re.compile(r"^mailto:"))

            contact_parts = []
            if consultant_match:
                contact_parts.append(consultant_match.group(1).strip())
            if phone_link:
                contact_parts.append(phone_link.get_text(strip=True))
            if email_link:
                contact_parts.append(email_link.get_text(strip=True))
            if contact_parts:
                details["Contact Details"] = " · ".join(contact_parts)
    except requests.RequestException as e:
        print(f"[WARN] Precise: не удалось открыть страницу вакансии {url}: {e}")

    if details.get("Requirements"):
        details["description"] = details.pop("Requirements")

    if details:
        return details

    # Запасной вариант — если разметка страницы не совпала с ожидаемой,
    # берём хотя бы то, что уже есть в API (описание/локация/email)
    for page in range(1, 3):
        job_list = _fetch_page(page)
        if not job_list:
            break

        for item in job_list:
            if not isinstance(item, dict):
                continue

            item_url = _absolute_url(item.get("URL") or item.get("apply_url") or "")
            if item_url != url:
                continue

            if item.get("location_label"):
                details["Location"] = item["location_label"]

            body = _strip_html(item.get("job_description") or item.get("short_description") or item.get("job_body") or "")
            if body:
                details["description"] = body

            contact = item.get("consultant_email") or item.get("apply_email")
            if contact:
                details["Contact Details"] = contact

            pay = item.get("pay_description")
            if pay:
                details["Salary"] = pay

            return details

    return details


if __name__ == "__main__":
    found = fetch_jobs()
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found[:10]:
        print("-", j["title"], "->", j["url"])
        print("  ", j["description"][:200])

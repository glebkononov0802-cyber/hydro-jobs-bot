"""
sources/precise.py

Парсер вакансий с сайта Precise Consultants (preciseconsultants.com).
Сайт построен на платформе Applyflow — вакансии полностью грузятся
через JS, но сам виджет обращается к открытому JSON API:

    https://account-api-uk.applyflow.com/api/seeker/v1/search-job

Это общий API для множества сайтов на Applyflow, поэтому важно
отправлять Referer/Origin именно preciseconsultants.com — иначе API
не поймёт, чей это запрос.

Точная структура JSON-ответа не проверена вживую (нет доступа к
браузеру из среды разработки), поэтому здесь много отладочных
принтов и "гибкое" угадывание имён полей — потребуется скорее всего
одна-две правки по логам первого реального запуска, как было с
другими более сложными источниками (OceanCrew, Insight Overseas).
"""

from __future__ import annotations
import requests

API_URL = "https://account-api-uk.applyflow.com/api/seeker/v1/search-job"

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


def _find_job_list(data) -> list | None:
    """Пытается найти список вакансий в JSON-ответе под разными
    вероятными именами ключей, потому что точная схема не проверена."""
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return None

    for key in ("jobs", "results", "items", "records", "data"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _find_job_list(value)
            if nested:
                return nested

    return None


def fetch_jobs(max_pages: int = 2) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "precise"}
    """
    jobs: list[dict] = []

    for page in range(1, max_pages + 1):
        params = {"url": "/", "facet": 1, "allow_backfill": "true", "page": page}

        resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=20)
        print(f"[DEBUG] Precise страница {page}: HTTP статус {resp.status_code}")

        if resp.status_code != 200:
            print(f"[DEBUG] Precise: тело ответа при ошибке: {resp.text[:300]}")
            break

        try:
            data = resp.json()
        except ValueError:
            print("[DEBUG] Precise: ответ не является JSON")
            print(f"[DEBUG] Precise: начало тела ответа: {resp.text[:300]}")
            break

        if isinstance(data, dict):
            print(f"[DEBUG] Precise: верхнеуровневые ключи JSON: {list(data.keys())}")

        job_list = _find_job_list(data)
        if not job_list:
            print("[DEBUG] Precise: не удалось найти список вакансий в JSON-ответе")
            break

        print(f"[DEBUG] Precise: вакансий на странице {page}: {len(job_list)}")
        if job_list:
            first = job_list[0]
            if isinstance(first, dict):
                print(f"[DEBUG] Precise: ключи первой вакансии: {list(first.keys())}")

        for item in job_list:
            if not isinstance(item, dict):
                continue

            title = item.get("title") or item.get("jobTitle") or item.get("job_title") or ""
            url = (
                item.get("url") or item.get("applyUrl") or item.get("apply_url")
                or item.get("link") or item.get("jobUrl") or ""
            )
            if not title or not url:
                continue

            if url.startswith("/"):
                url = "https://www.preciseconsultants.com" + url

            description_parts = []
            for key in ("description", "summary", "excerpt", "location", "city", "region", "country", "employmentType", "startDate", "salary"):
                value = item.get(key)
                if value:
                    description_parts.append(f"{key}: {value}")

            jobs.append({
                "title": title,
                "url": url,
                "description": " ".join(description_parts),
                "source": "precise",
            })

        if len(job_list) == 0:
            break

    print(f"[DEBUG] Precise: всего вакансий собрано: {len(jobs)}")
    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Пока не реализовано полноценно — структура страницы вакансии
    (или отдельного API-эндпоинта для одной вакансии) не проверена.
    Возвращает пустой словарь, сообщение уйдёт с тем описанием,
    что уже собрано в fetch_jobs из полей API.
    """
    return {}


if __name__ == "__main__":
    found = fetch_jobs()
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found[:10]:
        print("-", j["title"], "->", j["url"])
        print("  ", j["description"][:200])

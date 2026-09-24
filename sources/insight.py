"""
sources/insight.py

Парсер вакансий с сайта Insight Overseas (insightoverseas.com/jobs).

ВАЖНАЯ ОСОБЕННОСТЬ: это Next.js/React-приложение с аккордеоном.
В обычном серверном HTML полностью отрендерена только ПЕРВАЯ
(открытая) вакансия — у остальных видна лишь короткая сводка
(заголовок, номер, локация/срок одной строкой), а полное описание
и ссылка на страницу вакансии подгружаются уже в браузере.

Поэтому вместо парсинга видимой вёрстки мы читаем JSON, который
Next.js почти всегда встраивает в HTML целиком — тег
<script id="__NEXT_DATA__">. Он должен содержать данные ВСЕХ
вакансий, а не только открытой, независимо от того, что видно
на экране.

Это более "хрупкий" источник, чем UTM/AGR/OceanCrew — структура
JSON может не совпасть с тем, что мы предполагаем, и потребуется
donастройка по логам после первого реального запуска.
"""

from __future__ import annotations
import json
import re
import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://insightoverseas.com/jobs"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}


def _find_job_dicts(node, found=None):
    """
    Рекурсивно обходит JSON-структуру и собирает словари, похожие
    на вакансию — то есть содержащие одновременно 'title' и что-то
    вроде номера/ссылки/идентификатора.
    """
    if found is None:
        found = []

    if isinstance(node, dict):
        keys_lower = {k.lower() for k in node.keys()}
        if "title" in keys_lower and any(
            k in keys_lower for k in ("referencenumber", "reference", "slug", "id", "jrn")
        ):
            found.append(node)
        for value in node.values():
            _find_job_dicts(value, found)
    elif isinstance(node, list):
        for item in node:
            _find_job_dicts(item, found)

    return found


def _job_dict_to_entry(job: dict) -> dict | None:
    title = job.get("title") or job.get("Title") or ""
    if not title:
        return None

    slug = job.get("slug") or job.get("Slug")
    reference = (
        job.get("referenceNumber") or job.get("reference")
        or job.get("jrn") or job.get("id")
    )

    if slug:
        url = f"https://insightoverseas.com/jobs/{slug}"
    elif reference:
        ref_slug = re.sub(r"[^a-z0-9]+", "-", str(reference).lower()).strip("-")
        title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        url = f"https://insightoverseas.com/jobs/{title_slug}-{ref_slug}"
    else:
        return None

    description_parts = []

    location = job.get("location") or job.get("Location")
    if location:
        description_parts.append(f"Location: {location}.")

    duration = job.get("duration") or job.get("Duration")
    if duration:
        description_parts.append(f"Duration: {duration}.")

    start = job.get("start") or job.get("startDate") or job.get("Start")
    if start:
        description_parts.append(f"Start: {start}.")

    base_desc = job.get("description") or job.get("summary") or job.get("shortDescription") or ""
    if base_desc:
        description_parts.append(str(base_desc))

    positions = job.get("positions") or job.get("openPositions")
    if isinstance(positions, list) and positions:
        description_parts.append("Positions: " + ", ".join(str(p) for p in positions) + ".")

    return {
        "title": str(title),
        "url": url,
        "description": " ".join(description_parts),
        "source": "insight",
    }


def _load_next_data() -> dict | None:
    resp = requests.get(LISTING_URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    print(f"[DEBUG] Insight Overseas HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)}")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    script_tag = soup.find("script", id="__NEXT_DATA__")

    if not script_tag or not script_tag.string:
        print("[DEBUG] Insight Overseas: тег __NEXT_DATA__ не найден на странице")
        return None

    try:
        return json.loads(script_tag.string)
    except json.JSONDecodeError as e:
        print(f"[DEBUG] Insight Overseas: не удалось распарсить __NEXT_DATA__ как JSON: {e}")
        return None


def fetch_jobs(max_pages: int = 1) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "insight"}
    """
    data = _load_next_data()
    if data is None:
        return []

    job_dicts = _find_job_dicts(data)
    print(f"[DEBUG] Insight Overseas: найдено объектов, похожих на вакансию: {len(job_dicts)}")
    if job_dicts:
        print(f"[DEBUG] Insight Overseas: ключи первого объекта: {list(job_dicts[0].keys())}")

    jobs = []
    for job in job_dicts:
        entry = _job_dict_to_entry(job)
        if entry:
            jobs.append(entry)

    return jobs


def fetch_job_details(url: str) -> dict:
    """
    У Insight Overseas все нужные поля уже приходят вместе со списком
    (см. fetch_jobs) — благодаря __NEXT_DATA__ у нас сразу есть полное
    описание, а не только сводка. Поэтому просто заново находим нужную
    вакансию по URL среди уже распарсенных данных.
    """
    data = _load_next_data()
    if data is None:
        return {}

    job_dicts = _find_job_dicts(data)
    for job in job_dicts:
        entry = _job_dict_to_entry(job)
        if entry and entry["url"] == url:
            details = {"description": entry["description"], "full_description": False}

            location = job.get("location") or job.get("Location")
            if location:
                details["Location"] = location

            duration = job.get("duration") or job.get("Duration")
            if duration:
                details["Duration"] = duration

            start = job.get("start") or job.get("startDate") or job.get("Start")
            if start:
                details["Start Date"] = start

            return details

    return {}


if __name__ == "__main__":
    found = fetch_jobs()
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found[:10]:
        print("-", j["title"], "->", j["url"])

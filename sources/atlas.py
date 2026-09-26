"""
sources/atlas.py

Парсер вакансий с сайта Atlas NextWave (atlasnextwave.com/jobs),
категория Hydrographic Survey.

Особенность вёрстки: каждая карточка вакансии — это ОДНА ссылка <a>,
внутри которой уже лежит и заголовок, и локация/тип контракта/дата,
и краткое описание вместе. Поэтому вместо поиска заголовков (h2/h3)
как на других сайтах, тут ищем сразу ссылки на страницы вакансий
(atlasnextwave.com/job/<slug>/) и разбираем текст внутри.

Структура ответа не проверена вживую (нет доступа к браузеру из среды
разработки) — заложены отладочные принты для быстрой донастройки.
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

CATEGORY_URL = "https://atlasnextwave.com/jobs/job-category/hydrographic-survey/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

JOB_LINK_RE = re.compile(r"^https://atlasnextwave\.com/job/[a-z0-9\-]+/?$")


def fetch_jobs(max_pages: int = 3) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "atlas"}
    """
    jobs: list[dict] = []
    seen_hrefs: set[str] = set()

    for page_num in range(1, max_pages + 1):
        url = CATEGORY_URL if page_num == 1 else f"{CATEGORY_URL}page/{page_num}/?orderby=newest"

        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        print(f"[DEBUG] Atlas NextWave страница {page_num}: {url}")
        print(f"[DEBUG] HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)}")
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        candidate_links = [
            a for a in soup.find_all("a", href=True)
            if JOB_LINK_RE.match(a["href"].split("?")[0].rstrip("/") + "/")
        ]
        print(f"[DEBUG] Atlas NextWave: найдено ссылок на вакансии (с дублями): {len(candidate_links)}")

        found_on_page = 0
        for link in candidate_links:
            href = link["href"].split("?")[0].rstrip("/") + "/"
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            heading = link.find(["h2", "h3", "h4"])
            full_text = link.get_text(" ", strip=True)

            if heading:
                title = heading.get_text(strip=True)
                description = full_text.replace(title, "", 1).strip()
            else:
                # заголовка нет отдельным тегом — берём текст до первого "•"
                title = full_text.split("•")[0].strip()
                description = full_text

            if not title:
                continue

            jobs.append({
                "title": title,
                "url": href,
                "description": description,
                "source": "atlas",
            })
            found_on_page += 1

        print(f"[DEBUG] Atlas NextWave вакансий найдено на странице: {found_on_page}")
        if found_on_page == 0:
            break

    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу конкретной вакансии и пытается вытащить
    Location/Contract Type/Start Date, если они есть в узнаваемом виде,
    плюс более полное описание из основного текстового блока.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    details: dict = {}

    h1 = soup.find("h1")
    if h1:
        description_parts = []
        node = h1.find_next_sibling()
        steps = 0
        while node and steps < 8:
            text = node.get_text(" ", strip=True)
            if text and not re.match(r"^(Apply|Share|Related Jobs)\b", text, re.I):
                description_parts.append(text)
            node = node.find_next_sibling()
            steps += 1
        if description_parts:
            details["description"] = " ".join(description_parts)

    return details


if __name__ == "__main__":
    found = fetch_jobs(max_pages=1)
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found:
        print("-", j["title"], "->", j["url"])
        print("  ", j["description"][:150])

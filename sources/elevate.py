"""
sources/elevate.py

Парсер вакансий с сайта Elevate Offshore (elevateoffshore.com/vacancies).
Обычный серверный WordPress-сайт, requests + BeautifulSoup достаточно.

Удобная особенность: на самой странице списка уже видны Job Category,
Location, Start Date и обрезанный Job Description — почти как готовый
дайджест. Полное (необрезанное) описание и все поля дополнительно
подтягиваем со страницы конкретной вакансии в fetch_job_details.

Используем сразу фильтр по категории Survey, чтобы не тащить лишнее
(ROV/Other area(s) тоже могут быть релевантны отчасти, но keyword-фильтр
и так их обработает).
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.elevateoffshore.com/vacancies/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

JOB_LINK_RE = re.compile(r"^https://www\.elevateoffshore\.com/vacancies/[a-z0-9\-]+/?$")


def fetch_jobs(max_pages: int = 3) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "elevate"}
    """
    jobs: list[dict] = []

    for page_num in range(1, max_pages + 1):
        url = BASE_URL if page_num == 1 else f"{BASE_URL}page/{page_num}/"

        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        print(f"[DEBUG] Elevate Offshore страница {page_num}: {url}")
        print(f"[DEBUG] HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)}")

        if resp.status_code == 404:
            print(f"[DEBUG] Elevate Offshore: страница {page_num} не существует (404) — конец пагинации")
            break

        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        headings = soup.find_all(["h2", "h3"])

        found_on_page = 0
        for heading in headings:
            link = heading.find("a", href=True)
            if not link:
                continue

            href = link["href"].split("?")[0].rstrip("/") + "/"
            if not JOB_LINK_RE.match(href):
                continue

            title = link.get_text(strip=True)
            if not title:
                continue

            # Короткая сводка (Job Category/Location/Start Date/обрезанное
            # описание) — текст между этим заголовком и следующим
            block_parts = []
            node = heading.find_next_sibling()
            steps = 0
            while node and node.name not in ("h2", "h3") and steps < 10:
                text = node.get_text(" ", strip=True)
                if text:
                    block_parts.append(text)
                node = node.find_next_sibling()
                steps += 1

            jobs.append({
                "title": title,
                "url": href,
                "description": " ".join(block_parts),
                "source": "elevate",
            })
            found_on_page += 1

        print(f"[DEBUG] Elevate Offshore вакансий найдено на странице: {found_on_page}")
        if found_on_page == 0:
            break

    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу конкретной вакансии и вытаскивает Job Category,
    Location, Start Date и полное (необрезанное) описание.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    details: dict = {}
    full_text = soup.get_text(" ", strip=True)

    category_match = re.search(r"Job Category:\s*(.+?)\s*(?:Location:|Start Date:|Job Description:|$)", full_text)
    if category_match:
        details["Category"] = category_match.group(1).strip()

    location_match = re.search(r"Location:\s*(.+?)\s*(?:Start Date:|Job Category:|Job Description:|$)", full_text)
    if location_match:
        details["Location"] = location_match.group(1).strip()

    start_match = re.search(r"Start Date:\s*(.+?)\s*(?:Location:|Job Category:|Job Description:|$)", full_text)
    if start_match:
        details["Start Date"] = start_match.group(1).strip()

    desc_match = re.search(
        r"Job Description:\s*(.+?)\s*(?:Apply Now\b|Read more\b|Related Jobs\b|$)",
        full_text,
        re.S,
    )
    if desc_match:
        description = desc_match.group(1).strip()

        # Часто сайт повторяет заголовок вакансии первой строкой описания —
        # убираем этот дубль, раз название уже есть в самом сообщении
        h1 = soup.find("h1")
        title_text = h1.get_text(strip=True) if h1 else ""
        if title_text and description.lower().startswith(title_text.lower()):
            description = description[len(title_text):].strip(" –—-:")

        details["description"] = description
        # Тут часто идёт полезный блок Requirements сразу за описанием —
        # не обрезаем как у других источников, чтобы не терять его
        details["description_limit"] = 900

        # SOW (scope of work) — отдельной строкой перед описанием
        sow_match = re.search(
            r"SOW:\s*(.+?)(?:\s+Requi|\s+Software|\s+Location:|\s+Duration:|\s+Accommodation|$)",
            description,
            re.I,
        )
        if sow_match:
            details["Scope"] = sow_match.group(1).strip().rstrip(".")

        # Если внутри самого описания есть своя строка "Location:" — она
        # точнее общего поля с сайта (то часто просто страна/офис),
        # поэтому перебивает уже найденную выше Location
        inline_location_match = re.search(
            r"Location:\s*(.+?)(?:\s+(?:Mob|Mobilisation|SOW|Duration|Software|Requi|Accommodation)\b|$)",
            description,
            re.I,
        )
        if inline_location_match:
            details["Location"] = inline_location_match.group(1).strip().rstrip(".")

    return details


if __name__ == "__main__":
    found = fetch_jobs(max_pages=1)
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found:
        print("-", j["title"], "->", j["url"])

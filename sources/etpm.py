"""
sources/etpm.py

Парсер вакансий с сайта ETPM (etpm.co.uk), категория Survey & Inspection.
Обычный WordPress/Elementor-сайт, requests + BeautifulSoup достаточно.

Особенность страницы вакансии: после заголовка идёт просто набор строк
вида "Label: значение" (Job Role, Location, Start Date, Duration,
Vaccination Status, Experience, Other Info) — ничего сложного,
просто разбираем каждую строку по шаблону "Label: value".
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://www.etpm.co.uk/category/current-vacancies/survey-inspection/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}


def fetch_jobs(max_pages: int = 1) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "etpm"}
    """
    jobs: list[dict] = []

    for page_num in range(1, max_pages + 1):
        url = LISTING_URL if page_num == 1 else f"{LISTING_URL}page/{page_num}/"

        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        print(f"[DEBUG] ETPM страница {page_num}: {url}")
        print(f"[DEBUG] HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)}")
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        headings = soup.find_all(["h2", "h3"])

        found_on_page = 0
        for heading in headings:
            link = heading.find("a", href=True)
            if not link:
                continue

            href = link["href"].split("?")[0].rstrip("/") + "/"
            if "etpm.co.uk" not in href or "/category/" in href:
                continue

            title = link.get_text(strip=True)
            if not title:
                continue

            jobs.append({
                "title": title,
                "url": href,
                "description": "",  # полное описание подтянется через fetch_job_details
                "source": "etpm",
            })
            found_on_page += 1

        print(f"[DEBUG] ETPM вакансий найдено на странице: {found_on_page}")
        if found_on_page == 0:
            break

    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу конкретной вакансии ETPM и разбирает строки
    вида "Label: значение" (Job Role, Location, Start Date, Duration,
    Vaccination Status, Experience, Other Info).
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    details: dict = {}

    h1 = soup.find("h1")
    if not h1:
        return details

    node = h1.find_next_sibling()
    steps = 0
    while node and steps < 15:
        # Читаем с переносом строки, потому что ETPM часто кладёт все
        # поля (Job Role/Location/Start Date/...) в один <p> через <br>,
        # а не отдельными элементами
        block_text = node.get_text("\n", strip=True)
        if block_text:
            if re.search(r"^Apply For This Role$", block_text, re.I | re.M):
                break
            for line in block_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                label_match = re.match(r"^([A-Za-z][A-Za-z /]{2,30}):\s*(.+)$", line)
                if label_match:
                    label = label_match.group(1).strip()
                    value = label_match.group(2).strip()
                    details[label] = value
        node = node.find_next_sibling()
        steps += 1

    # "Other Info" обычно содержит визовые/сертификационные требования —
    # используем как основное описание вакансии
    if "Other Info" in details:
        details["description"] = details.pop("Other Info")

    return details


if __name__ == "__main__":
    found = fetch_jobs()
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found:
        print("-", j["title"], "->", j["url"])

"""
sources/utm.py

Парсер вакансий с сайта UTM Consultants (utmconsultants.com).
Сайт отдаёт обычный серверный HTML — никакого JS/AJAX-эндпоинта
искать не нужно, requests + BeautifulSoup достаточно.

Берём страницу с фильтром по категории Hydrographic Survey, но
собираем ВСЕ заголовки-вакансии на странице (не только с category=hydro),
потому что финальную релевантность всё равно решает job_filter.py —
так мы не пропустим смежные роли (ROV, Marine и т.д.), если UTM
поместит их в другую категорию.
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.utmconsultants.com/jobs/"
LISTING_URL = f"{BASE_URL}?professionid=6858&search=1&matador-categories=hydrographic-survey"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

JOB_LINK_RE = re.compile(r"^https://www\.utmconsultants\.com/jobs/[a-z0-9\-]+/?$")


def fetch_jobs(max_pages: int = 2) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "utm"}
    """
    jobs: list[dict] = []
    url = LISTING_URL

    for page_num in range(max_pages):
        resp = requests.get(url, headers=HEADERS, timeout=20)

        print(f"[DEBUG] Страница {page_num + 1}: {url}")
        print(f"[DEBUG] HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)} символов")

        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        page_title = soup.title.get_text(strip=True) if soup.title else "(нет title)"
        print(f"[DEBUG] <title> страницы: {page_title}")

        headings = soup.find_all(["h2", "h3", "h4"])
        print(f"[DEBUG] Найдено заголовков h2/h3/h4 на странице: {len(headings)}")

        for heading in headings:
            link = heading.find("a", href=True)
            if not link:
                continue

            href = link["href"].split("?")[0].rstrip("/") + "/"
            if not JOB_LINK_RE.match(href):
                continue
            if href.rstrip("/") == BASE_URL.rstrip("/"):
                continue

            title = link.get_text(strip=True)
            if not title:
                continue

            # Собираем текст между этим заголовком и следующим —
            # там обычно лежат "Type:", "Job #...", дата и описание.
            description_parts = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ("h2", "h3", "h4"):
                    break
                text = sibling.get_text(" ", strip=True)
                if text:
                    description_parts.append(text)

            jobs.append({
                "title": title,
                "url": href,
                "description": " ".join(description_parts),
                "source": "utm",
            })

        next_link = soup.find("a", string=re.compile(r"Next", re.I))
        if next_link and next_link.get("href"):
            url = next_link["href"]
        else:
            break

    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу конкретной вакансии и вытаскивает структурированные
    поля (Location, Work Type, Start Date, Duration, Software и т.п.)
    из первой таблицы на странице, плюс текст описания между
    первой и второй таблицей.

    Вызывается только для новых вакансий — не на каждый прогон бота.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    details: dict = {}
    tables = soup.find_all("table")

    if tables:
        first_table = tables[0]
        for row in first_table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True).rstrip(":")
                value = cells[1].get_text(strip=True)
                if key and value:
                    details[key] = value

        # Описание — текст между первой таблицей (Location/...) и
        # второй таблицей (Reference Number/Contact/...)
        description_parts = []
        node = first_table.find_next_sibling()
        while node and node.name != "table":
            text = node.get_text(" ", strip=True)
            if text:
                description_parts.append(text)
            node = node.find_next_sibling()
        details["description"] = " ".join(description_parts)

    return details


if __name__ == "__main__":
    found = fetch_jobs()
    print(f"Найдено вакансий на странице: {len(found)}\n")
    for j in found:
        print("-", j["title"], "->", j["url"])

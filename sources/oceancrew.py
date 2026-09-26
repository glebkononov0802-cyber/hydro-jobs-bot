"""
sources/oceancrew.py

Парсер вакансий с сайта OceanCrew (oceancrew.org).
Обычный серверный HTML, requests + BeautifulSoup достаточно.

Берём сразу две готовые категории сайта — Surveyors и Survey Engineer,
чтобы не полагаться только на одну.

Особенность: у OceanCrew нет открытого email для отклика в HTML —
отклик идёт через кнопку "Apply Job", которая требует регистрации на
сайте. Поэтому Contact Details тут не собираем, только Company/Salary/
Posted/description.
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

CATEGORY_URLS = [
    "https://oceancrew.org/vacancies/offshore/surveyors",
    "https://oceancrew.org/vacancies/offshore/survey-engineer",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

JOB_LINK_RE = re.compile(r"^https://oceancrew\.org/vacancies/offshore/[a-z0-9\-]+/[a-z0-9\-_]+$")


def _fetch_category(base_url: str, max_pages: int) -> list[dict]:
    jobs: list[dict] = []

    for page_num in range(1, max_pages + 1):
        url = base_url if page_num == 1 else f"{base_url}?page={page_num}"

        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        print(f"[DEBUG] OceanCrew страница {page_num}: {url}")
        print(f"[DEBUG] HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)}")

        if resp.status_code == 404:
            print(f"[DEBUG] OceanCrew: страница {page_num} не существует (404) — конец пагинации")
            break

        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        headings = soup.find_all(["h2", "h3"])

        found_on_page = 0
        for heading in headings:
            link = heading.find("a", href=True)
            if not link:
                continue

            href = link["href"].split("?")[0].rstrip("/")
            if not JOB_LINK_RE.match(href):
                continue

            title = link.get_text(strip=True)
            if not title:
                continue

            description_parts = []
            node = heading.find_next_sibling()
            steps = 0
            while node and node.name not in ("h2", "h3") and steps < 6:
                text = node.get_text(" ", strip=True)
                if text:
                    description_parts.append(text)
                node = node.find_next_sibling()
                steps += 1

            jobs.append({
                "title": title,
                "url": href,
                "description": " ".join(description_parts),
                "source": "oceancrew",
            })
            found_on_page += 1

        print(f"[DEBUG] OceanCrew вакансий найдено на странице: {found_on_page}")
        if found_on_page == 0:
            break

    return jobs


def fetch_jobs(max_pages: int = 2) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "oceancrew"}
    Собирает сразу из категорий Surveyors и Survey Engineer.
    """
    jobs: list[dict] = []
    for category_url in CATEGORY_URLS:
        jobs.extend(_fetch_category(category_url, max_pages))
    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу вакансии OceanCrew и вытаскивает Company,
    Salary (если указана), Posted (дата публикации) и description.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    details: dict = {}

    h1 = soup.find("h1")

    if h1:
        company_link = h1.find_next("a", href=re.compile(r"/companies/"))
        if company_link:
            details["Company"] = company_link.get_text(strip=True)

        date_node = h1.find_previous(string=re.compile(r"^\d{2}-\d{2}-\d{4}$"))
        if date_node:
            details["Posted"] = date_node.strip()

    salary_match = re.search(r"Offered Salary\s*([^\n]+)", soup.get_text(" ", strip=True))
    if salary_match:
        salary_value = salary_match.group(1).strip()
        if salary_value and "not specified" not in salary_value.lower():
            details["Salary"] = salary_value

    # Локация: сначала пробуем найти "Location: ..." прямо в тексте описания
    # (так часто пишут, например, DOF Group), иначе берём из скобок в
    # заголовке вакансии — например "Surveyor for Offshore Vessel (Italy)"
    full_text = soup.get_text(" ", strip=True)
    location_match = re.search(
        r"Location:\s*(.+?)(?:\s+(?:Job Description|Company Overview|Job Type|Vessel Type|Employment Details):|$)",
        full_text,
    )
    if location_match:
        location_value = location_match.group(1).strip().rstrip(".")
        if location_value:
            details["Location"] = location_value
    elif h1:
        title_text = h1.get_text(strip=True)
        paren_match = re.search(r"\(([^)]+)\)\s*$", title_text)
        if paren_match:
            details["Location"] = paren_match.group(1).strip()

    section_match = re.search(
        r"Job description\s*(.+?)\s*Job Info\b",
        full_text,
        re.S | re.I,
    )
    if section_match:
        desc_block = section_match.group(1).strip()
        # убираем служебный подзаголовок, который есть почти всегда
        desc_block = re.sub(
            r"^Role details, requirements and important context from the employer\.?\s*",
            "",
            desc_block,
            flags=re.I,
        )
        # некоторые агентства дублируют метку "Job Description:" внутри — убираем и её
        desc_block = re.sub(r"^Job Description:\s*", "", desc_block, flags=re.I)
        details["description"] = desc_block.strip()

    # У OceanCrew бывают как короткие описания (2-3 строки), так и длинные
    # портянки с Key Responsibilities/Requirements/Employment Details.
    # Ставим лимит побольше, чем у других источников (550 вместо 220) —
    # этого хватает на суть (локация, софт, позиция), а не на всё подряд.
    details["description_limit"] = 550

    return details


if __name__ == "__main__":
    found = fetch_jobs(max_pages=1)
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found[:5]:
        print("-", j["title"], "->", j["url"])

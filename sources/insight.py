"""
sources/insight.py

Парсер вакансий с сайта Insight Overseas (insightoverseas.com/jobs).

Разгадка по этому сайту: список вакансий (аккордеон) — React-компонент,
но у КАЖДОЙ вакансии, даже свёрнутой, в обычном HTML видны заголовок
и номер (например "1361/2026") — этого достаточно, чтобы предсказуемо
построить URL страницы этой вакансии. А вот сама страница конкретной
вакансии (https://insightoverseas.com/jobs/<slug>) — это уже ОБЫЧНЫЙ
серверный HTML без React, там ничего специального парсить не нужно.

Поэтому: со страницы списка берём только заголовок+номер (и короткую
сводную строку локация/срок/направление), а полные детали (Positions,
Location, Start, Duration, Posted) забираем со страницы самой вакансии.
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://insightoverseas.com/jobs"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}


def _slug_from_title_and_ref(title: str, reference: str) -> str:
    title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    ref_slug = reference.replace("/", "-")
    return f"https://insightoverseas.com/jobs/{title_slug}-{ref_slug}"


def fetch_jobs(max_pages: int = 1) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "insight"}
    Описание на этом этапе — короткая сводная строка со страницы списка
    (локация · срок · направление), полное описание подтянется позже
    через fetch_job_details только для реально новых вакансий.
    """
    resp = requests.get(LISTING_URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    print(f"[DEBUG] Insight Overseas HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)}")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    headings = soup.find_all(["h2", "h3"])
    print(f"[DEBUG] Insight Overseas: найдено заголовков h2/h3: {len(headings)}")

    jobs = []
    for heading in headings:
        title = heading.get_text(strip=True)
        if not title:
            continue

        # Номер вакансии — первый следующий сосед вида "1234/2026"
        ref_node = heading.find_next_sibling()
        if not ref_node:
            continue
        ref_text = ref_node.get_text(strip=True)
        ref_match = re.match(r"^(\d+/\d{4})$", ref_text)
        if not ref_match:
            # Это не заголовок вакансии (например "We are looking for you.")
            continue
        reference = ref_match.group(1)

        # Сводная строка — следующий сосед после номера
        summary_node = ref_node.find_next_sibling()
        summary = summary_node.get_text(" ", strip=True) if summary_node else ""

        url = _slug_from_title_and_ref(title, reference)

        jobs.append({
            "title": title,
            "url": url,
            "description": summary,
            "source": "insight",
        })

    print(f"[DEBUG] Insight Overseas: вакансий собрано: {len(jobs)}")
    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу конкретной вакансии (обычный серверный HTML)
    и вытаскивает Positions, Location, Start Date, Duration, Posted
    и полное описание.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    details: dict = {}

    h1 = soup.find("h1")
    if not h1:
        return details

    # Positions — список <li> под заголовком "Positions"
    positions_heading = soup.find(["h2", "h3", "h4"], string=re.compile(r"^Positions$", re.I))
    if positions_heading:
        ul = positions_heading.find_next("ul")
        if ul:
            items = [li.get_text(strip=True) for li in ul.find_all("li")]
            if items:
                details["Positions"] = ", ".join(items)

    # Простые поля-подписи: Location / Start / Duration / Posted —
    # заголовок, а значение сразу следующим элементом
    field_map = {"Location": "Location", "Start": "Start Date", "Duration": "Duration", "Posted": "Posted"}
    for label, key in field_map.items():
        label_node = soup.find(["h2", "h3", "h4"], string=re.compile(rf"^{label}$", re.I))
        if label_node:
            value_node = label_node.find_next_sibling()
            value = value_node.get_text(" ", strip=True) if value_node else ""
            if value:
                details[key] = value

    # Описание — текст между заголовком (h1) и заголовком "Positions"
    description_parts = []
    node = h1.find_next_sibling()
    steps = 0
    while node and steps < 6:
        if node.name in ("h2", "h3", "h4") and re.search(r"^Positions$", node.get_text(strip=True), re.I):
            break
        text = node.get_text(" ", strip=True)
        if text:
            description_parts.append(text)
        node = node.find_next_sibling()
        steps += 1
    details["description"] = " ".join(description_parts)

    return details


if __name__ == "__main__":
    found = fetch_jobs()
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found:
        print("-", j["title"], "->", j["url"])
        print("  ", j["description"])


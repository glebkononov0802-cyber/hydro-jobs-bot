"""
sources/sa_world.py

Парсер вакансий SA World / SA Operations (Stephenson Operations B.V.),
sa-world.com/open-vacancies.html. Joomla, серверный HTML, ~10 вакансий на
страницу, около 16 страниц (?start=0,10,20,...).

На странице списка у каждой вакансии — заголовок-ссылка и маркированные поля:
Day Rate / Location / Duration / Mob Date / Sector / Point of Contact /
Contact Phone / Job Reference Number.

ВНИМАНИЕ: на сайте много устаревших объявлений (референсы 2025-xxx, даже
2023), поэтому в main.py для этого источника включён "тихий первый запуск":
все уже существующие вакансии просто помечаются как виденные без отправки.
Email рекрутера на сайте скрыт защитой от спам-ботов — есть только имя и телефон.
"""

from __future__ import annotations
import re
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.sa-world.com/open-vacancies.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

JOB_PATH_RE = re.compile(
    r"^/open-vacancies/open-vacancies-(?:operations|staff|executive)/[a-z0-9\-]+\.html$"
)
FIELD_RE = re.compile(
    r"^(Day Rate|Location|Duration|Mob Date|Sector|Point of Contact|Contact Phone|Job Reference Number)\s*:\s*(.+)$"
)


def _parse_listing(soup: BeautifulSoup, page_url: str = BASE_URL) -> list[dict]:
    jobs: list[dict] = []
    seen_here: set[str] = set()

    for heading in soup.find_all(["h2", "h3"]):
        link = heading.find("a", href=True)
        if not link:
            continue
        # В сыром HTML ссылки обычно относительные (/open-vacancies/...) —
        # приводим к абсолютным и проверяем по пути
        parsed = urlparse(urljoin(page_url, link["href"]))
        if not JOB_PATH_RE.match(parsed.path):
            continue
        href = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if href in seen_here:
            continue
        seen_here.add(href)

        title = link.get_text(strip=True)
        if not title:
            continue

        parts = []
        node = heading.find_next_sibling()
        steps = 0
        while node and node.name not in ("h2", "h3") and steps < 8:
            text = node.get_text(" ", strip=True)
            if text and not text.startswith("Read more"):
                parts.append(text)
            node = node.find_next_sibling()
            steps += 1

        jobs.append({
            "title": title,
            "url": href,
            "description": " ".join(parts),
            "source": "sa",
        })

    return jobs


def fetch_jobs(max_pages: int = 16) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "sa"}
    Обходит страницы ?start=0,10,20,... пока находятся новые вакансии.
    """
    jobs: list[dict] = []
    known: set[str] = set()

    for page_idx in range(max_pages):
        url = BASE_URL if page_idx == 0 else f"{BASE_URL}?start={page_idx * 10}"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        print(f"[DEBUG] SA World страница {page_idx + 1}: {url} — статус {resp.status_code}")

        if resp.status_code == 404:
            break
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        all_page_jobs = _parse_listing(soup, url)
        print(
            f"[DEBUG] SA World: заголовков h2/h3: {len(soup.find_all(['h2', 'h3']))}, "
            f"ссылок на вакансии: {len(all_page_jobs)}"
        )
        if page_idx == 0 and not all_page_jobs:
            # Первая страница без единой вакансии — это не "пусто", а поломка
            # (сайт изменил разметку / отдал заглушку). Пусть сработает алерт.
            raise RuntimeError("SA World: на первой странице не найдено ни одной вакансии — возможно, изменилась разметка сайта")

        page_jobs = [j for j in all_page_jobs if j["url"] not in known]
        if not page_jobs:
            print(f"[DEBUG] SA World: на странице {page_idx + 1} новых вакансий нет — конец")
            break

        known.update(j["url"] for j in page_jobs)
        jobs.extend(page_jobs)

    print(f"[DEBUG] SA World: всего вакансий собрано: {len(jobs)}")
    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу вакансии и вытаскивает Location, Mob Date, Sector,
    Day Rate, Duration, контакт (имя + телефон) и требования кандидата.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]

    # Поля вида "Location: North Sea" — берём первое вхождение каждого
    # (дальше на странице блок Job Summary их дублирует)
    fields: dict[str, str] = {}
    for line in lines:
        m = FIELD_RE.match(line)
        if m:
            fields.setdefault(m.group(1), m.group(2).strip())

    details: dict = {}

    if fields.get("Location"):
        details["Location"] = fields["Location"]
    if fields.get("Mob Date"):
        details["Start Date"] = fields["Mob Date"]
    if fields.get("Duration"):
        details["Duration"] = fields["Duration"]
    if fields.get("Sector"):
        details["Scope"] = fields["Sector"]

    day_rate = fields.get("Day Rate", "")
    if day_rate:
        # "Freelance assignment on day rate" — это тип работы, а "€5,500 gross
        # per month" / "550 EUR/day" — уже оплата
        if re.search(r"\d", day_rate):
            details["Salary"] = day_rate
        else:
            details["Work Type"] = day_rate

    contact_parts = [fields.get("Point of Contact", ""), fields.get("Contact Phone", "")]
    contact = " ".join(p for p in contact_parts if p)
    if contact:
        details["Contact Details"] = contact

    # Требования: раздел CANDIDATE PROFILE до HOW TO APPLY
    description = ""
    upper = [l.upper() for l in lines]
    if "CANDIDATE PROFILE" in upper:
        start = upper.index("CANDIDATE PROFILE") + 1
        end = upper.index("HOW TO APPLY") if "HOW TO APPLY" in upper[start:] else len(lines)
        profile_lines = [l for l in lines[start:end] if l not in ("---",)]
        description = " ".join(profile_lines)
    if not description:
        # у части вакансий нет разделов — берём основной текст после Job Summary
        if "Job Summary" in lines:
            idx = lines.index("Job Summary") + 1
            body = []
            for l in lines[idx:]:
                if l.upper().startswith(("WHO WE ARE", "HOW TO APPLY")):
                    break
                if FIELD_RE.match(l):
                    continue
                body.append(l)
            description = " ".join(body)

    if description:
        details["description"] = description
        details["description_limit"] = 500

    return details


if __name__ == "__main__":
    found = fetch_jobs(max_pages=2)
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found[:10]:
        print("-", j["title"], "->", j["url"])

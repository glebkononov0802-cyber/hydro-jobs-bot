"""
sources/ips.py

Парсер вакансий iPS Powerful People (нидерландское агентство), раздел
Seismic & Survey: ipspowerfulpeople.com/vacancies/expertises-seismic-survey/
Обычный серверный сайт (Drupal), requests + BeautifulSoup достаточно.

Список: карточки-ссылки вида "Online Surveyor 20 August 2026 Seismic & Survey
<короткое описание>" -> /vacancies/seismic-survey/<номер>/<slug>/.
Страница вакансии: Short Description / Function Description / Requirements,
имя и email рекрутера, блок IN SHORT (категория, код страны, континент, дата).

Берём только раздел Seismic & Survey: остальные разделы (сварщики, механики,
финансы...) к вашей специальности не относятся.
"""

from __future__ import annotations
import re
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://ipspowerfulpeople.com/vacancies/expertises-seismic-survey/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

JOB_PATH_RE = re.compile(r"^/vacancies/seismic-survey/[A-Za-z0-9\-]+/[A-Za-z0-9\-]+/?$")
DATE_RE = re.compile(
    r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b"
)
COUNTRY_CODES = {
    "GB": "United Kingdom", "UK": "United Kingdom", "US": "United States",
    "NL": "Netherlands", "DE": "Germany", "DK": "Denmark", "NO": "Norway",
    "FR": "France", "IT": "Italy", "MX": "Mexico", "SA": "Saudi Arabia",
    "AE": "UAE", "QA": "Qatar", "PL": "Poland", "BR": "Brazil",
}


def _parse_listing(soup: BeautifulSoup, page_url: str) -> list[dict]:
    jobs: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        parsed = urlparse(urljoin(page_url, a["href"]))
        if not JOB_PATH_RE.match(parsed.path):
            continue
        url = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/"
        if url in seen:
            continue
        seen.add(url)

        text = a.get_text(" ", strip=True)
        heading = a.find(["h2", "h3", "h4", "h5", "strong"])

        m = DATE_RE.search(text)
        if heading and heading.get_text(strip=True):
            title = heading.get_text(strip=True)
        elif m:
            title = text[:m.start()].strip()
        else:
            title = text.split("  ")[0].strip()
        if not title:
            continue

        description = ""
        if m:
            rest = text[m.end():].strip()
            description = re.sub(r"^Seismic\s*&\s*Survey\s*", "", rest).strip()

        jobs.append({
            "title": title,
            "url": url,
            "description": description,
            "source": "ips",
        })

    return jobs


def fetch_jobs(max_pages: int = 3) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "ips"}
    """
    jobs: list[dict] = []
    known: set[str] = set()

    for page_num in range(1, max_pages + 1):
        url = LISTING_URL if page_num == 1 else f"{LISTING_URL}page/{page_num}/"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        print(f"[DEBUG] iPS страница {page_num}: {url} — статус {resp.status_code}")

        if resp.status_code == 404:
            break
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        if page_num == 1 and "vacanc" not in title.lower():
            raise RuntimeError(f"iPS: неожиданная страница, title='{title}'")

        page_jobs = [j for j in _parse_listing(soup, url) if j["url"] not in known]
        if not page_jobs:
            if page_num == 1 and "/vacancies/seismic-survey/" in resp.text:
                raise RuntimeError("iPS: ссылки на вакансии есть, но карточки не разобраны — возможно, изменилась разметка")
            break
        known.update(j["url"] for j in page_jobs)
        jobs.extend(page_jobs)

    print(f"[DEBUG] iPS: всего вакансий собрано: {len(jobs)}")
    return jobs


_SECTION_HEADINGS = ("Short Description", "Function Description", "Requirements")


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу вакансии и вытаскивает Start Date, Location, описание
    (Short Description + Requirements) и контакт рекрутера (имя + email).
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    details: dict = {}

    # Дата старта — первая строка с датой после заголовка страницы
    h1 = soup.find("h1")
    h1_text = h1.get_text(strip=True) if h1 else ""
    begin = lines.index(h1_text) + 1 if h1_text in lines else 0
    for l in lines[begin:begin + 12]:
        m = DATE_RE.search(l)
        if m:
            details["Start Date"] = m.group(1)
            break

    # Блок IN SHORT: категория, код страны, континент, дата
    if "IN SHORT" in lines:
        short = lines[lines.index("IN SHORT") + 1:lines.index("IN SHORT") + 5]
        if len(short) >= 3:
            code = short[1].strip()
            country = COUNTRY_CODES.get(code.upper(), code)
            continent = short[2].strip()
            if not DATE_RE.search(continent):
                details["Location"] = f"{country}, {continent}" if continent else country
            else:
                details["Location"] = country

    # Разделы описания
    sections: dict[str, list[str]] = {}
    current = None
    for l in lines[begin:]:
        if l.startswith("If this isn") or l in ("POWER YOUR CAREER", "IN SHORT"):
            break
        if l in _SECTION_HEADINGS:
            current = l
            sections[current] = []
            continue
        if current:
            sections[current].append(l)

    short_desc = " ".join(sections.get("Short Description", []))
    requirements = "; ".join(sections.get("Requirements", []))
    description = short_desc
    if requirements:
        description = f"{description} Requirements: {requirements}".strip()
    if description:
        details["description"] = description
        details["description_limit"] = 550

    # Контакт: имя стоит строкой перед email рекрутера (общий info@ пропускаем)
    for i, l in enumerate(lines):
        m = re.search(r"[\w.\-]+@ipspowerfulpeople\.com", l)
        if m and not m.group(0).lower().startswith("info@"):
            email = m.group(0)
            name = lines[i - 1] if i > 0 and "@" not in lines[i - 1] and len(lines[i - 1]) < 60 else ""
            details["Contact Details"] = "\n".join(p for p in (name, email) if p)
            break

    return details


if __name__ == "__main__":
    for j in fetch_jobs():
        print("-", j["title"], "->", j["url"])

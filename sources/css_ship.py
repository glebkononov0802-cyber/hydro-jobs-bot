"""
sources/css_ship.py

Парсер вакансий с сайта CSS – Channel Ship Services (css-shipservices.com/jobs).
Обычный серверный HTML (Craft CMS), requests + BeautifulSoup достаточно.

На странице списка — карточки: название, Start date, Category, Location и
ссылка "View job role". Сайт пишет "16 open jobs", а на первой странице
видно только 6 + кнопка "Load More" — как именно грузится остальное, вживую
не проверено, поэтому для следующих страниц пробуем оба вероятных формата
(/jobs/p2 как в Craft CMS и ?page=2) и смотрим, появились ли новые вакансии.

Страница вакансии: разделы Position / Experience / Documentation, блок
Details (Category/Location/Start Date) и контакт рекрутера.
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.css-shipservices.com"
LISTING_URL = f"{BASE_URL}/jobs"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

JOB_LINK_RE = re.compile(r"^https://www\.css-shipservices\.com/job/[a-z0-9\-]+/?$")


def _parse_listing(soup: BeautifulSoup) -> list[dict]:
    """Разбирает карточки вакансий на одной странице списка."""
    jobs: list[dict] = []
    seen_here: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"].split("?")[0].rstrip("/")
        if not JOB_LINK_RE.match(href) or href in seen_here:
            continue
        seen_here.add(href)

        heading = link.find_previous(["h2", "h3"])
        title = heading.get_text(strip=True) if heading else ""
        if not title:
            continue

        # Карточка: берём текст вокруг ссылки, чтобы достать категорию/локацию/дату
        card = link.find_parent(["li", "article", "div"]) or link
        card_text = card.get_text("\n", strip=True)

        category = ""
        m = re.search(r"Category\s*\n\s*(.+)", card_text)
        if m:
            category = m.group(1).strip()
        location = ""
        m = re.search(r"Location\s*\n\s*(.+)", card_text)
        if m:
            location = m.group(1).strip()
        start = ""
        m = re.search(r"Start date\s*\n\s*(.+)", card_text, re.I)
        if m:
            start = m.group(1).strip()

        # "Survey - Engineer" -> "Survey Engineer", чтобы фильтр узнал фразу
        category_norm = category.replace(" - ", " ")

        jobs.append({
            "title": title,
            "url": href,
            "description": f"{category_norm}. {location}. Start {start}".strip(),
            "source": "css",
        })

    return jobs


def fetch_jobs(max_pages: int = 3) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "css"}
    """
    resp = requests.get(LISTING_URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    print(f"[DEBUG] CSS Ship Services страница 1: {LISTING_URL}")
    print(f"[DEBUG] HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)}")
    resp.raise_for_status()

    jobs = _parse_listing(BeautifulSoup(resp.text, "html.parser"))
    print(f"[DEBUG] CSS Ship Services вакансий на странице 1: {len(jobs)}")
    known_urls = {j["url"] for j in jobs}

    for page_num in range(2, max_pages + 1):
        candidates = [f"{LISTING_URL}/p{page_num}", f"{LISTING_URL}?page={page_num}"]
        added = 0

        for url in candidates:
            try:
                r = requests.get(url, headers=HEADERS, timeout=20)
            except requests.RequestException as e:
                print(f"[DEBUG] CSS Ship Services: {url} — ошибка запроса: {e}")
                continue
            r.encoding = "utf-8"
            print(f"[DEBUG] CSS Ship Services пробуем {url}: статус {r.status_code}")
            if r.status_code != 200:
                continue

            new_jobs = [
                j for j in _parse_listing(BeautifulSoup(r.text, "html.parser"))
                if j["url"] not in known_urls
            ]
            if new_jobs:
                for j in new_jobs:
                    known_urls.add(j["url"])
                jobs.extend(new_jobs)
                added = len(new_jobs)
                print(f"[DEBUG] CSS Ship Services страница {page_num}: новых вакансий {added}")
                break

        if not added:
            print(f"[DEBUG] CSS Ship Services: страница {page_num} новых вакансий не дала — конец")
            break

    print(f"[DEBUG] CSS Ship Services: всего вакансий собрано: {len(jobs)}")
    return jobs


def _value_after(lines: list[str], label: str, start_idx: int = 0) -> str:
    """Значение — следующая строка после строки-метки вида 'Start Date:'."""
    for i in range(start_idx, len(lines) - 1):
        if lines[i].rstrip(":").strip().lower() == label.lower() and lines[i].endswith(":"):
            return lines[i + 1].strip()
    return ""


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу вакансии и вытаскивает Location, Start Date, Duration,
    Experience, описание (Position + Documentation) и контакт рекрутера.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    details: dict = {}

    # Блок Details (после заголовка "The details")
    details_idx = lines.index("The details") if "The details" in lines else 0
    location = _value_after(lines, "Location", details_idx)
    if location:
        details["Location"] = location
    start_date = _value_after(lines, "Start Date", details_idx)
    if start_date:
        details["Start Date"] = start_date

    # Разделы описания: Position / Experience / Documentation
    sections: dict[str, list[str]] = {}
    if "Description" in lines:
        current = None
        free_text: list[str] = []
        for line in lines[lines.index("Description") + 1:]:
            if line.startswith("Interested?") or line in ("Details", "The details"):
                break
            if line.endswith(":") and line.rstrip(":") in ("Position", "Experience", "Documentation"):
                current = line.rstrip(":")
                sections[current] = []
                continue
            if current:
                sections[current].append(line)
            else:
                free_text.append(line)
        if not sections and free_text:
            sections["Position"] = free_text

    position_text = " ".join(sections.get("Position", []))
    docs_text = ", ".join(sections.get("Documentation", []))
    # убираем из Documentation служебную фразу про актуальность документов
    docs_text = re.sub(r"^For this job the following certificate/documents need to be up to date:\s*,?\s*", "", docs_text)

    duration_match = re.search(r"Duration:\s*(.+?)(?=\s+(?:Please|Note|Joining)\b|$)", position_text)
    if duration_match:
        details["Duration"] = duration_match.group(1).strip()

    if sections.get("Experience"):
        details["Experience"] = " ".join(sections["Experience"])

    description = position_text
    if docs_text:
        description = f"{description} Docs: {docs_text}".strip()
    if description:
        details["description"] = description
        details["description_limit"] = 600

    # Контакт: email из фразы "Please contact ...", имя — из блока "How to apply"
    # Имя и email берём из одного блока "How to apply" (имя + mailto-ссылка);
    # на сайте в тексте описания иногда указан другой человек — его почту
    # добавляем отдельной строкой, если она отличается
    full_text = "\n".join(lines)
    desc_email_match = re.search(r"contact\s+([\w.\-]+@css-shipservices\.com)", full_text, re.I)
    desc_email = desc_email_match.group(1) if desc_email_match else ""

    mailto = soup.find("a", href=re.compile(r"^mailto:"))
    apply_email = mailto["href"].replace("mailto:", "").strip() if mailto else ""

    name_match = re.search(r"How to apply:.*?contact\s+(\w+)\s+at", full_text, re.I | re.S)
    name = name_match.group(1) if name_match else ""

    contact_lines = []
    if name:
        contact_lines.append(name)
    if apply_email:
        contact_lines.append(apply_email)
    if desc_email and desc_email.lower() != apply_email.lower():
        contact_lines.append(desc_email)
    if contact_lines:
        details["Contact Details"] = "\n".join(contact_lines)

    return details


if __name__ == "__main__":
    found = fetch_jobs()
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found:
        print("-", j["title"], "->", j["url"])
        print("  ", j["description"])

"""
sources/wrs.py

Парсер вакансий WRS – Worldwide Recruitment Solutions, раздел Marine
(jobs.worldwide-rs.com/marine/). Обычный серверный WordPress (ATS Tracker-RMS).

Главная страница jobs.worldwide-rs.com забита американским строительством,
поэтому берём именно категорию Marine — там offshore/survey.

Страница вакансии: заголовок, потом текст с эмодзи-метками
(📍 Location: / ⏳ Duration: / 💻 Software: / 📅 ...), контактный email
(John.Graves@worldwide-rs.com) и блок ATS: Job type / Sector / Reference.
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://jobs.worldwide-rs.com/marine/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

JOB_LINK_RE = re.compile(r"^https://jobs\.worldwide-rs\.com/jobs/[a-z0-9\-]+/?$")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d]")
CUTOFF_RE = re.compile(r"\s+(?:Must|If interested|If you|Please|Send|EU/UK|Interested|Ideally)\b")
LABEL_RE = re.compile(
    r"(?<![A-Za-z])(Title|Mob Location|Location|Start Date|Duration|Software|Day Rate|Rate)\s*:\s*"
)


def _parse_listing(soup: BeautifulSoup) -> list[dict]:
    jobs: list[dict] = []
    seen_here: set[str] = set()

    for heading in soup.find_all(["h2", "h3"]):
        link = heading.find("a", href=True)
        if not link:
            continue
        href = link["href"].split("?")[0].rstrip("/") + "/"
        if not JOB_LINK_RE.match(href) or href in seen_here:
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
            if text and text != "View job":
                parts.append(text)
            node = node.find_next_sibling()
            steps += 1

        jobs.append({
            "title": title,
            "url": href,
            "description": " ".join(parts),
            "source": "wrs",
        })

    return jobs


def fetch_jobs(max_pages: int = 3) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "wrs"}
    """
    resp = requests.get(LISTING_URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    print(f"[DEBUG] WRS страница 1: {LISTING_URL}")
    print(f"[DEBUG] HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)}")
    resp.raise_for_status()

    jobs = _parse_listing(BeautifulSoup(resp.text, "html.parser"))
    print(f"[DEBUG] WRS вакансий на странице 1: {len(jobs)}")
    known = {j["url"] for j in jobs}

    # Следующие страницы: формат пагинации вживую не проверен — пробуем
    # оба варианта и останавливаемся, как только новых вакансий нет
    for page_num in range(2, max_pages + 1):
        added = 0
        for url in (f"{LISTING_URL}page/{page_num}/", f"{LISTING_URL}?paged={page_num}"):
            try:
                r = requests.get(url, headers=HEADERS, timeout=20)
            except requests.RequestException as e:
                print(f"[DEBUG] WRS: {url} — ошибка запроса: {e}")
                continue
            r.encoding = "utf-8"
            print(f"[DEBUG] WRS пробуем {url}: статус {r.status_code}")
            if r.status_code != 200:
                continue
            new_jobs = [j for j in _parse_listing(BeautifulSoup(r.text, "html.parser")) if j["url"] not in known]
            if new_jobs:
                known.update(j["url"] for j in new_jobs)
                jobs.extend(new_jobs)
                added = len(new_jobs)
                print(f"[DEBUG] WRS страница {page_num}: новых вакансий {added}")
                break
        if not added:
            break

    print(f"[DEBUG] WRS: всего вакансий собрано: {len(jobs)}")
    return jobs


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", EMOJI_RE.sub(" ", value)).strip(" .;,:-")


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу вакансии и вытаскивает Location, Start Date, Duration,
    Software, Rate, тип контракта, описание и контакт рекрутера.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    h1 = soup.find("h1")
    h1_text = h1.get_text(strip=True) if h1 else ""

    start = lines.index(h1_text) + 1 if h1_text in lines else 0
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith(("Location Not Specified", "Job type", "Apply now")):
            end = i
            break

    body_lines = [
        l for l in lines[start:end]
        if l.lower() not in ("back", "share", "apply", "sms", "email", "linkedin", "twitter", "facebook")
        and not l.startswith(("sms:", "mailto:", "http"))
    ]

    details: dict = {}
    desc_lines: list[str] = []

    for raw in body_lines:
        text = EMOJI_RE.sub(" ", raw)
        matches = list(LABEL_RE.finditer(text))
        if matches:
            for i, m in enumerate(matches):
                seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                raw_value = text[m.end():seg_end]
                cut = CUTOFF_RE.search(raw_value)
                if cut:
                    tail = _clean(re.sub(r"\s*If interested.*$", "", raw_value[cut.start():], flags=re.I))
                    raw_value = raw_value[:cut.start()]
                    if tail and not re.match(r"^(Interested|If interested|Send|Please)", tail, re.I):
                        desc_lines.append(tail)
                label, value = m.group(1), _clean(raw_value)
                if not value:
                    continue
                if label == "Location":
                    details.setdefault("Location", value)
                elif label == "Start Date":
                    details.setdefault("Start Date", value)
                elif label == "Duration":
                    details.setdefault("Duration", value)
                elif label == "Software":
                    details.setdefault("Software", value)
                elif label in ("Rate", "Day Rate"):
                    details.setdefault("Salary", value)
                elif label == "Title":
                    details.setdefault("Positions", value)
            continue

        if re.match(r"^(Interested|If interested|Send your CV|Follow )", _clean(text), re.I):
            continue
        if "@" in text:
            continue
        cleaned = _clean(text)
        if cleaned:
            desc_lines.append(cleaned)

    description = " ".join(desc_lines)
    if description:
        details["description"] = description
        details["description_limit"] = 450

    # Блок ATS (после описания): Job type Contract
    tail_text = " ".join(lines[end:])
    type_match = re.search(r"Job type\s+([A-Za-z\-]+)", tail_text)
    if type_match:
        details["Work Type"] = type_match.group(1)

    # Контакт: email рекрутера, имя — из локальной части (John.Graves -> John Graves)
    full_text = " ".join(lines)
    email_match = re.search(r"[\w.\-]+@worldwide-rs\.com", full_text)
    if email_match:
        email = email_match.group(0)
        parts = re.split(r"[._]", email.split("@")[0])
        name = " ".join(p.capitalize() for p in parts) if len(parts) >= 2 and all(len(p) > 1 for p in parts) else ""
        details["Contact Details"] = "\n".join(p for p in (name, email) if p)

    return details


if __name__ == "__main__":
    found = fetch_jobs()
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found:
        print("-", j["title"], "->", j["url"])

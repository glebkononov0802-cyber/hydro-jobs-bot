"""
sources/cmsourcing.py

Парсер вакансий CMSourcing (cmsourcing.global/jobs/) — UK-агентство, много
survey/geophysics/data processing контрактов (Online Surveyor, Data Processor,
Party Chief, Remote Data Processor...). Обычный серверный WordPress.

Список: карточки (название, локация, JOB-номер, "23 hours ago", короткое
описание, Start Date, Duration) со ссылкой /job-detail/?reference=JOB-xxxx.
Страница вакансии: Job No. / Location / Contact / Published / Start Date /
Specialisms / Contact email / Duration / Description — аккуратные пары
"заголовок -> значение".
"""

from __future__ import annotations
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

LISTING_URL = "https://www.cmsourcing.global/jobs/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}


def _is_job_link(href: str) -> bool:
    return "job-detail" in href and "reference=JOB-" in href


def _parse_listing(soup: BeautifulSoup, page_url: str = LISTING_URL) -> list[dict]:
    jobs: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        if not _is_job_link(a["href"]):
            continue
        url = urljoin(page_url, a["href"]).split("#")[0]
        if url in seen:
            continue
        seen.add(url)

        # Карточка = самый большой предок, внутри которого только одна ссылка
        # на вакансию (и он не разросся до половины страницы)
        container = a
        for parent in a.parents:
            hrefs = {x["href"] for x in parent.find_all("a", href=True) if _is_job_link(x["href"])}
            if len(hrefs) > 1:
                break
            if len([l for l in parent.get_text("\n").split("\n") if l.strip()]) > 20:
                break
            container = parent

        lines = [l.strip(" |\t") for l in container.get_text("\n").split("\n")]
        lines = [l for l in lines if l and l.lower() not in ("apply now", "read more")]
        if len(lines) < 3:
            continue

        # Название и локация стоят прямо перед номером JOB-xxxx — так надёжнее,
        # чем брать "первую строку карточки" (контейнер может зацепить меню)
        ref_idx = next((i for i, l in enumerate(lines) if re.fullmatch(r"JOB-\d+", l)), None)
        if ref_idx is not None and ref_idx >= 2:
            title, location = lines[ref_idx - 2], lines[ref_idx - 1]
        else:
            title, location = lines[0], lines[1]

        posted_idx = next((i for i, l in enumerate(lines) if l.lower().endswith(" ago")), None)
        snippet_lines = []
        if posted_idx is not None:
            for l in lines[posted_idx + 1:]:
                if l.startswith(("Start Date", "Duration")):
                    break
                snippet_lines.append(l)

        jobs.append({
            "title": title,
            "url": url,
            "description": f"{location}. {' '.join(snippet_lines)}".strip(),
            "source": "cmsourcing",
        })

    return jobs


def fetch_jobs(max_pages: int = 1) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "cmsourcing"}
    """
    resp = requests.get(LISTING_URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    print(f"[DEBUG] CMSourcing: {LISTING_URL} — статус {resp.status_code}, длина {len(resp.text)}")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = _parse_listing(soup, LISTING_URL)
    print(f"[DEBUG] CMSourcing: вакансий собрано: {len(jobs)}")

    if not jobs and "job-detail" in resp.text:
        # Ссылки на вакансии есть, а разобрать не удалось — разметка изменилась
        raise RuntimeError("CMSourcing: ссылки на вакансии есть, но карточки не разобраны — возможно, изменилась разметка")
    return jobs


def _value_after(lines: list[str], label: str, start: int = 0) -> str:
    for i in range(start, len(lines) - 1):
        if lines[i] == label:
            return lines[i + 1].strip()
    return ""


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу вакансии и вытаскивает Location, Start Date, Duration,
    дату публикации, описание и контакт (имя + email).
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    # Меню и футер тоже содержат слово "Contact" — ищем только после "Job No."
    base = lines.index("Job No.") if "Job No." in lines else 0

    details: dict = {}

    location = _value_after(lines, "Location", base)
    if location:
        details["Location"] = location
    start_date = _value_after(lines, "Start Date", base)
    if start_date:
        details["Start Date"] = start_date
    duration = _value_after(lines, "Duration", base)
    if duration:
        details["Duration"] = duration
    published = _value_after(lines, "Published", base)
    if published:
        details["Posted"] = published

    name = _value_after(lines, "Contact", base)
    email = _value_after(lines, "Contact email", base)
    contact = "\n".join(p for p in (name, email) if p)
    if contact:
        details["Contact Details"] = contact

    for i in range(base, len(lines)):
        if lines[i].startswith("Description:"):
            text = lines[i][len("Description:"):].lstrip("- ").strip()
            # описание иногда переносится на следующие строки до "Apply Now"
            for extra in lines[i + 1:]:
                if extra.lower().startswith("apply now"):
                    break
                text = f"{text} {extra}".strip()
            if text:
                details["description"] = text
                details["description_limit"] = 400
            break

    return details


if __name__ == "__main__":
    for j in fetch_jobs():
        print("-", j["title"], "->", j["url"])

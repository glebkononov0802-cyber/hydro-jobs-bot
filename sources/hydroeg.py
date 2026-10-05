"""
sources/hydroeg.py

Парсер вакансий Hydro Energy Group (hydroeg.com/jobposition). Сайт сделан на
Wix: вёрстка — "каша" из div без нормальных классов, поэтому разбираем не по
тегам, а по тексту страницы.

Каждая карточка в тексте выглядит так:
    Online Surveyor
    10027                      <- номер вакансии
    Australia                  <- локация
    [короткое описание]        <- бывает не всегда
    Start Date
    Employment Type
    21 December, 2026
    Contract
    Industry
    Expertise
    Survey                     <- категория
    EIVA                       <- ключевые навыки/ПО
    Apply Now

Страница отдаёт весь список дважды (десктопная и мобильная версии) — дубли
убираем по номеру вакансии.

Прямых ссылок на отдельные вакансии на hydroeg.com нет: кнопка Apply ведёт во
внешнюю систему exen.ai, которая запрещает автоматический доступ (robots) —
её НЕ трогаем. В сообщении даём ссылку на общий список и номер вакансии.
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

LIST_URL = "https://www.hydroeg.com/jobposition"
GENERAL_EMAIL = "engage@hydroeg.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

# кеш: url вакансии -> разобранные поля (чтобы не качать страницу второй раз
# при получении деталей в том же запуске)
_CACHE: dict[str, dict] = {}


def _load_lines() -> list[str]:
    resp = requests.get(LIST_URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    print(f"[DEBUG] Hydro Energy Group: {LIST_URL} — статус {resp.status_code}, длина {len(resp.text)}")
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]


def _parse(lines: list[str]) -> list[dict]:
    """Режем текст на блоки по кнопке 'Apply Now' и разбираем каждый."""
    jobs: dict[str, dict] = {}
    block_start = 0

    for i, line in enumerate(lines):
        if line != "Apply Now":
            continue
        block = lines[block_start:i]
        block_start = i + 1

        if "Start Date" not in block:
            continue
        sd = block.index("Start Date")

        # номер — последняя строка из одних цифр перед "Start Date";
        # название стоит прямо перед ним, локация — сразу после
        id_idx = next((j for j in range(sd - 1, -1, -1) if re.fullmatch(r"\d{3,6}", block[j])), None)
        if id_idx is None or id_idx < 1:
            continue
        job_id = block[id_idx]
        title = block[id_idx - 1]
        location = block[id_idx + 1] if id_idx + 1 < sd else ""
        description = " ".join(block[id_idx + 2:sd])

        after = block[sd + 1:]
        start = work_type = ""
        if "Employment Type" in after:
            et = after.index("Employment Type")
            if et + 1 < len(after):
                start = after[et + 1]
            if et + 2 < len(after):
                work_type = after[et + 2]
        tags: list[str] = []
        if "Expertise" in after:
            tags = after[after.index("Expertise") + 1:]

        jobs[job_id] = {
            "id": job_id,
            "title": title,
            "location": location,
            "description": description,
            "start": start,
            "work_type": work_type,
            "tags": tags,
        }

    return list(jobs.values())


def _job_url(job_id: str) -> str:
    # Фрагмент (#) нужен только как уникальный ключ для дедупликации —
    # страница по этому адресу открывается как обычный общий список
    return f"{LIST_URL}#job-{job_id}"


def fetch_jobs(max_pages: int = 1) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "hydroeg"}
    """
    lines = _load_lines()
    parsed = _parse(lines)
    print(f"[DEBUG] Hydro Energy Group: вакансий собрано: {len(parsed)}")

    if not parsed and "Apply Now" in lines:
        # Кнопки "Apply Now" есть, а вакансии не разобрались — изменилась вёрстка
        raise RuntimeError("Hydro Energy Group: найдены кнопки Apply Now, но вакансии не разобраны — возможно, изменилась разметка")

    jobs = []
    _CACHE.clear()
    for p in parsed:
        url = _job_url(p["id"])
        _CACHE[url] = p
        # в оценку фильтра идут и теги (EIVA/QINSy…) — они сильный сигнал
        text = f"{p['location']}. {p['description']} {' '.join(p['tags'])}".strip()
        jobs.append({
            "title": p["title"],
            "url": url,
            "description": text,
            "source": "hydroeg",
        })
    return jobs


def fetch_job_details(url: str) -> dict:
    """Детали из уже разобранного списка (или перечитываем страницу)."""
    p = _CACHE.get(url)
    if p is None:
        job_id = url.rsplit("job-", 1)[-1]
        p = next((x for x in _parse(_load_lines()) if x["id"] == job_id), None)
    if p is None:
        return {}

    details: dict = {
        "display_url": LIST_URL,
        "Contact Details": GENERAL_EMAIL,
        "Job ID": p["id"],  # номер — чтобы найти вакансию в общем списке
    }
    if p["location"]:
        details["Location"] = p["location"]
    if p["start"]:
        details["Start Date"] = p["start"]
    if p["work_type"]:
        details["Work Type"] = p["work_type"]
    if p["description"]:
        details["description"] = p["description"]
        details["description_limit"] = 400

    tags = p["tags"]
    if tags:
        details["Category"] = tags[0]          # обычно "Survey"
        if len(tags) > 1:
            details["Experience"] = ", ".join(tags[1:])
    return details


if __name__ == "__main__":
    for j in fetch_jobs():
        print("-", j["title"], "|", j["description"])

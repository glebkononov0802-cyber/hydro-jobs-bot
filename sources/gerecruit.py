"""
sources/gerecruit.py

"Сторож" для gerecruit.com (Geo-Environmental Recruitment).

Сейчас на сайте 0 вакансий ("Sorry, no results were found"), поэтому как
выглядит карточка вакансии — неизвестно, и нормальный парсер писать не из чего.
Вместо этого бот следит за страницей поиска и, как только пустая надпись
пропадёт, присылает ОДНО сообщение в "сыром" виде: текст страницы с
результатами + найденные ссылки. По этому примеру потом пишем настоящий парсер
и заменяем этот режим.

Фильтр по ключевым словам для этого сообщения отключён (флаг force) —
нужно увидеть любую вакансию, даже не по теме.
"""

from __future__ import annotations
import hashlib
import re
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.gerecruit.com/job-search?hideSub=1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}

# Служебные разделы сайта — ссылки на них вакансиями не считаем
NAV_PATH_PREFIXES = (
    "/about-us", "/the-team", "/clients", "/news", "/contact-us", "/terms",
    "/user/", "/job-alerts", "/vacancies/browse", "/job-search", "/images/",
    "/system/", "/removeaccount", "/media/",
)


def _load_page() -> BeautifulSoup:
    resp = requests.get(SEARCH_URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    print(f"[DEBUG] gerecruit: HTTP статус {resp.status_code}, длина ответа {len(resp.text)}")
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else ""
    if "vacanc" not in title.lower():
        # Не та страница (заглушка, редирект, смена структуры) — это поломка
        raise RuntimeError(f"gerecruit: неожиданная страница, title='{title}'")
    return soup


def _is_empty(soup: BeautifulSoup) -> bool:
    return "no results were found" in soup.get_text(" ", strip=True).lower()


def _candidate_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Ссылки, похожие на вакансии: внутренние, не из служебных разделов."""
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(SEARCH_URL, href)
        parsed = urlparse(full)
        if "gerecruit.com" not in parsed.netloc:
            continue
        if parsed.path in ("", "/") or parsed.path.startswith(NAV_PATH_PREFIXES):
            continue
        text = a.get_text(" ", strip=True)
        if not text or full in seen:
            continue
        seen.add(full)
        result.append((text, full))
    return result


def _results_text(soup: BeautifulSoup) -> str:
    """Текст блока результатов: после фильтров (последний пункт 'Contract')
    и до формы подписки."""
    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    start = 0
    for i, line in enumerate(lines):
        if line == "Contract":
            start = i + 1
            break
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith(("The email you provided", "Contact", "Registered Office")):
            end = i
            break
    return "\n".join(lines[start:end])


def fetch_jobs(max_pages: int = 1) -> list[dict]:
    """
    Пока вакансий нет — возвращает пустой список (это нормальное состояние).
    Как только они появились — одна "сырая" запись с флагом force.
    """
    soup = _load_page()

    if _is_empty(soup):
        print("[DEBUG] gerecruit: вакансий нет (Sorry, no results were found)")
        return []

    links = _candidate_links(soup)
    text = _results_text(soup)
    digest = hashlib.sha1(
        ("|".join(sorted(u for _, u in links)) or text).encode("utf-8")
    ).hexdigest()[:10]

    # Для разбора структуры: кусок сырого HTML в лог Actions
    print("[GERECRUIT-RAW] кандидаты в ссылки на вакансии:")
    for t, u in links[:15]:
        print(f"[GERECRUIT-RAW]   {t} -> {u}")
    print("[GERECRUIT-RAW] текст блока результатов (начало):")
    print(text[:1500])

    print(f"[DEBUG] gerecruit: на странице есть результаты, ссылок-кандидатов: {len(links)}")
    return [{
        "title": "gerecruit: на сайте появились вакансии",
        "url": f"{SEARCH_URL}#raw-{digest}",
        "description": "",
        "source": "gerecruit",
        "force": True,
    }]


def fetch_job_details(url: str) -> dict:
    """Сырой дамп: ссылки-кандидаты + текст блока результатов."""
    soup = _load_page()
    if _is_empty(soup):
        return {"raw_mode": True, "description": "Страница уже снова пустая."}

    links = _candidate_links(soup)
    parts = []
    if links:
        parts.append("Ссылки на странице:")
        parts.extend(f"• {t} — {u}" for t, u in links[:8])
        parts.append("")
    parts.append(_results_text(soup))

    return {
        "raw_mode": True,
        "description": "\n".join(parts).strip(),
        "description_limit": 1800,
        "display_url": SEARCH_URL,
    }


if __name__ == "__main__":
    print(fetch_jobs())

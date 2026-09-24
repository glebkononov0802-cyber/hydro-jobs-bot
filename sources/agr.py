"""
sources/agr.py

Парсер вакансий с сайта AGR (agrl.co.uk).
Тоже обычный серверный HTML — requests + BeautifulSoup достаточно,
JS/AJAX не требуется.

Особенность сайта: нет аккуратных таблиц с полями, как у UTM.
- В списке каждая вакансия имеет ссылку с текстом ровно "Full Description",
  которая ведёт на страницу вакансии — это самый надёжный якорь.
- На странице вакансии поля идут как заголовок ("Sector:", "Point of
  Contact:" и т.п.) + значение сразу после него, плюс "голые" строки
  зарплаты/локации/даты под заголовком "Job Summary".
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.agrl.co.uk/jobs/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HydroJobsBot/1.0; personal use)"
}


def fetch_jobs(max_pages: int = 3) -> list[dict]:
    """
    Возвращает список вакансий вида:
    {"title": str, "url": str, "description": str, "source": "agr"}
    """
    jobs: list[dict] = []

    for page_num in range(1, max_pages + 1):
        url = BASE_URL if page_num == 1 else f"{BASE_URL}page/{page_num}/"

        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        print(f"[DEBUG] AGR страница {page_num}: {url}")
        print(f"[DEBUG] HTTP статус: {resp.status_code}, длина ответа: {len(resp.text)}")
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Самый надёжный якорь — ссылки с текстом ровно "Full Description"
        full_desc_links = [
            a for a in soup.find_all("a", href=True)
            if a.get_text(strip=True) == "Full Description"
        ]
        print(f"[DEBUG] Найдено ссылок 'Full Description': {len(full_desc_links)}")

        if not full_desc_links:
            break

        for link in full_desc_links:
            href = link["href"].split("?")[0].rstrip("/") + "/"

            # Заголовок вакансии — ближайший предыдущий h2/h3/h4,
            # обрезаем всё начиная с "Share this Job"
            heading = link.find_previous(["h2", "h3", "h4"])
            raw_title = heading.get_text(" ", strip=True) if heading else ""
            title = re.split(r"Share this Job", raw_title, flags=re.I)[0].strip()
            if not title:
                continue

            # Описание — текст между этой ссылкой и следующим заголовком
            description_parts = []
            container = link.find_parent(["p", "div"]) or link
            node = container.find_next_sibling()
            steps = 0
            while node and steps < 15:
                if node.name in ("h2", "h3", "h4"):
                    break
                text = node.get_text(" ", strip=True)
                if text:
                    description_parts.append(text)
                node = node.find_next_sibling()
                steps += 1

            jobs.append({
                "title": title,
                "url": href,
                "description": " ".join(description_parts),
                "source": "agr",
            })

        # Пагинация: если на странице меньше вакансий, чем обычно —
        # видимо, дошли до конца, но проще всего просто попробовать
        # следующую страницу и остановиться, если ссылок не найдено
        # (проверяется в начале следующей итерации цикла).

    return jobs


def fetch_job_details(url: str) -> dict:
    """
    Открывает страницу конкретной вакансии AGR и вытаскивает:
    Salary, Location, Start Date (из блока Job Summary),
    Sector, Contact Details (email из "How to Apply"), description.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    details: dict = {}

    # Поля вида "Sector:" / "Point of Contact:" / "Contact Phone:" —
    # заголовок + значение сразу следующим элементом
    for heading in soup.find_all(["h2", "h3", "h4"]):
        label = heading.get_text(strip=True).rstrip(":")
        if label in ("Sector", "Point of Contact", "Contact Phone", "Job Reference Number"):
            value_node = heading.find_next_sibling()
            value = value_node.get_text(" ", strip=True) if value_node else ""
            if value:
                details[label] = value

    # Job Summary: обычно три "голых" строки подряд — зарплата, локация, дата
    summary_text_node = soup.find(string=re.compile(r"Job Summary", re.I))
    if summary_text_node:
        heading = summary_text_node.find_parent(["h2", "h3", "h4"])
        lines = []
        node = heading.find_next_sibling() if heading else None
        while node and len(lines) < 3:
            text = node.get_text(" ", strip=True)
            if text:
                lines.append(text)
            node = node.find_next_sibling()
        if len(lines) >= 1:
            details["Salary"] = lines[0]
        if len(lines) >= 2:
            details["Location"] = lines[1]
        if len(lines) >= 3:
            details["Start Date"] = lines[2]

    # Описание — текст рядом с "Job Description:"
    job_desc_label = soup.find(string=re.compile(r"Job Description:", re.I))
    if job_desc_label:
        parent = job_desc_label.find_parent(["p", "div", "strong", "b"])
        text_after = ""
        if parent:
            full_text = parent.get_text(" ", strip=True)
            text_after = re.sub(r"^.*Job Description:\s*", "", full_text, flags=re.I)
        if not text_after and parent:
            sib = parent.find_next_sibling()
            text_after = sib.get_text(" ", strip=True) if sib else ""
        if text_after:
            details["description"] = text_after

    # Email для отклика — из блока "How to Apply:"
    apply_label = soup.find(string=re.compile(r"How to Apply:", re.I))
    if apply_label:
        parent = apply_label.find_parent(["p", "div"])
        if parent:
            text = parent.get_text(" ", strip=True)
            email_match = re.search(r"[\w.\-]+@[\w.\-]+", text)
            if email_match:
                details["Contact Details"] = email_match.group(0)

    return details


if __name__ == "__main__":
    found = fetch_jobs(max_pages=1)
    print(f"\nНайдено вакансий: {len(found)}\n")
    for j in found[:5]:
        print("-", j["title"], "->", j["url"])

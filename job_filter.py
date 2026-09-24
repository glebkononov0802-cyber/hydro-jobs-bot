"""
job_filter.py

Keyword-scoring фильтр для Hydro Jobs Bot.
Каждая вакансия (title + description) прогоняется через взвешенный
список ключевых слов. Если итоговый score выше порога — вакансия
считается релевантной.
"""

from dataclasses import dataclass, field
import re


POSITIVE_KEYWORDS: dict[str, int] = {
    "online surveyor": 12,
    "senior online surveyor": 14,
    "party chief": 12,
    "senior surveyor": 10,
    "hydrographic surveyor": 12,
    "marine surveyor": 8,
    "survey engineer": 6,
    "survey technician": 6,
    "site surveyor": 8,
    "project surveyor": 8,
    "data processor": 10,
    "senior data processor": 12,
    "multibeam data processor": 14,
    "remote data processor": 10,
    "remote online surveyor": 12,
    "remote": 2,

    "qinsy": 10,
    "eiva": 10,
    "qimera": 8,
    "kongsberg": 6,
    "mbes": 8,
    "multibeam": 8,
    "usbl": 6,
    "navipac": 8,
    "lbl": 6,

    "offshore survey": 8,
    "marine survey": 6,
    "geophysical survey": 6,
    "geotechnical survey": 6,
    "cable survey": 6,
    "wind farm survey": 6,
    "dredging survey": 5,
    "rov survey": 5,
    "seabed": 4,

    "freelance": 6,
    "contract": 4,
    "day rate": 6,
    "rotation": 3,
    "asap": 2,
}

NEGATIVE_KEYWORDS: dict[str, int] = {
    "land surveyor": -15,
    "land survey": -12,
    "quantity surveyor": -15,
    "civil surveyor": -12,
    "gis analyst": -8,
    "gis only": -10,
    "intern": -10,
    "internship": -10,
    "student": -8,
    "junior": -6,
    "permanent position": -6,
    "full-time employee": -6,
}

# Вакансия проходит дальше, если в тексте встретилось хотя бы одно
# из этих слов ИЛИ хотя бы одно из POSITIVE_KEYWORDS длиной от 2 слов
# (например "data processor") — это защищает от полного мусора вроде
# "Quantity Surveyor" без дублирования всего списка ключевых ролей здесь.
REQUIRE_ANY_OF = [
    "survey", "surveyor", "hydro", "offshore", "marine",
    "qinsy", "eiva", "mbes", "multibeam", "geophysic", "geotechnical",
    "data processor",
]

DEFAULT_THRESHOLD = 8


@dataclass
class ScoredJob:
    title: str
    url: str
    score: int
    source: str = ""
    matched_positive: list = field(default_factory=list)
    matched_negative: list = field(default_factory=list)


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-zа-я0-9\s\-/]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def score_job(title: str, description: str = "", url: str = "", source: str = "") -> ScoredJob:
    full_text = _normalize(f"{title} {description}")

    if not any(kw in full_text for kw in REQUIRE_ANY_OF):
        return ScoredJob(title=title, url=url, score=-999, source=source)

    score = 0
    matched_pos, matched_neg = [], []

    for kw, weight in POSITIVE_KEYWORDS.items():
        if kw in full_text:
            score += weight
            matched_pos.append(kw)

    for kw, weight in NEGATIVE_KEYWORDS.items():
        if kw in full_text:
            score += weight
            matched_neg.append(kw)

    return ScoredJob(title=title, url=url, score=score, source=source,
                      matched_positive=matched_pos, matched_negative=matched_neg)


def filter_jobs(jobs: list[dict], threshold: int = DEFAULT_THRESHOLD) -> list[ScoredJob]:
    scored = [
        score_job(j.get("title", ""), j.get("description", ""), j.get("url", ""), j.get("source", ""))
        for j in jobs
    ]
    relevant = [s for s in scored if s.score >= threshold]
    relevant.sort(key=lambda s: s.score, reverse=True)
    return relevant

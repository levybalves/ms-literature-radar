from __future__ import annotations

import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .models import Article


def load_topics(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["topics"]


def classify(article: Article, topics: list[dict[str, Any]]) -> Article:
    title = _normalize(article.title)
    abstract = _normalize(article.abstract)
    controlled = _normalize(
        " ".join(
            article.mesh_terms
            + article.keywords
            + article.author_keywords
            + article.subjects
        )
    )
    enriched_context = _normalize(
        " ".join(
            [
                article.publisher,
                article.article_type,
                *article.affiliations,
            ]
        )
    )

    topic_scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}

    for topic in topics:
        score = 0.0
        hits: list[str] = []

        for keyword, weight in topic["keywords"].items():
            needle = _normalize(keyword)
            if not needle:
                continue

            title_hits = _count_phrase(title, needle)
            abstract_hits = _count_phrase(abstract, needle)
            controlled_hits = _count_phrase(controlled, needle)
            enriched_hits = _count_phrase(enriched_context, needle)

            # Título > vocabulário controlado/keywords > metadados enriquecidos > resumo.
            # Log1p evita que repetição de um mesmo termo domine o escore.
            raw_hits = (
                (title_hits * 3.0)
                + (controlled_hits * 2.2)
                + (enriched_hits * 1.4)
                + abstract_hits
            )
            if raw_hits:
                score += float(weight) * (1.0 + math.log1p(raw_hits))
                hits.append(keyword)

        topic_scores[topic["id"]] = round(score, 3)
        if hits:
            matched[topic["id"]] = sorted(set(hits), key=str.lower)

    best_topic = max(topic_scores, key=topic_scores.get) if topic_scores else "general"
    if not topic_scores or topic_scores.get(best_topic, 0.0) <= 0:
        best_topic = "general"

    article.primary_topic = best_topic
    article.topic_scores = topic_scores
    article.matched_keywords = matched
    article.relevance_score = calculate_relevance(article)
    return article


def calculate_relevance(article: Article) -> float:
    """
    Escore de triagem, não "qualidade científica".

    Componentes:
      - 35 pontos: artigo já está dentro da busca de EM.
      - até 35: força de correspondência temática.
      - até 20: recência.
      - até 10: tipo de publicação, para facilitar triagem.
    """
    score = 35.0

    best_topic_score = max(article.topic_scores.values(), default=0.0)
    score += min(35.0, best_topic_score * 2.4)

    days_old = _days_old(article.online_date or article.pub_date)
    if days_old is not None:
        if days_old <= 7:
            score += 20
        elif days_old <= 14:
            score += 17
        elif days_old <= 30:
            score += 13
        elif days_old <= 60:
            score += 8
        elif days_old <= 120:
            score += 4

    types = " | ".join(article.publication_types + ([article.article_type] if article.article_type else [])).lower()
    if "meta-analysis" in types or "systematic review" in types:
        score += 10
    elif "randomized controlled trial" in types:
        score += 10
    elif "clinical trial" in types:
        score += 8
    elif "review" in types:
        score += 5

    return round(min(score, 100.0), 1)


def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _count_phrase(haystack: str, needle: str) -> int:
    if not haystack or not needle:
        return 0
    # Limites alfanuméricos ajudam com termos curtos como PET/EBV sem quebrar HLA-DRB1.
    pattern = rf"(?<!\w){re.escape(needle)}(?!\w)"
    return len(re.findall(pattern, haystack, flags=re.IGNORECASE))


def _days_old(pub_date: str) -> int | None:
    if not pub_date:
        return None
    formats = ("%Y-%m-%d", "%Y-%m", "%Y")
    for fmt in formats:
        try:
            dt = datetime.strptime(pub_date, fmt).date()
            return max((date.today() - dt).days, 0)
        except ValueError:
            pass
    return None

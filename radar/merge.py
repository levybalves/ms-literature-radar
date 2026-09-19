from __future__ import annotations

import re
from typing import Iterable

from .models import Article, normalize_doi


LIST_FIELDS = (
    "authors",
    "publication_types",
    "mesh_terms",
    "keywords",
    "affiliations",
    "author_keywords",
    "subjects",
    "fulltext_urls",
    "supplementary_urls",
    "discovery_sources",
    "enrichment_sources",
    "enrichment_notes",
)


def merge_articles(base: Article, incoming: Article) -> Article:
    """Mescla duas representações do mesmo trabalho sem perder metadados."""
    base.ensure_identity()
    incoming.ensure_identity()

    # Identificadores externos.
    if not base.pmid and incoming.pmid:
        base.pmid = incoming.pmid
    if not base.doi and incoming.doi:
        base.doi = normalize_doi(incoming.doi)
    if not base.pmc_id and incoming.pmc_id:
        base.pmc_id = incoming.pmc_id
    base.source_ids = {**incoming.source_ids, **base.source_ids}

    # O título da primeira fonte costuma ser bom; prefira o mais informativo se o atual estiver vazio.
    if not base.title and incoming.title:
        base.title = incoming.title

    # Para resumo, prefira a versão mais longa/não vazia.
    if len(incoming.abstract or "") > len(base.abstract or ""):
        base.abstract = incoming.abstract

    for field_name in ("journal", "publisher", "article_type", "publisher_url", "graphical_abstract_url"):
        if not getattr(base, field_name) and getattr(incoming, field_name):
            setattr(base, field_name, getattr(incoming, field_name))

    # Data principal: preserve a fonte já escolhida, mas preencha se ausente.
    if not base.pub_date and incoming.pub_date:
        base.pub_date = incoming.pub_date
    if not base.online_date and incoming.online_date:
        base.online_date = incoming.online_date

    for field_name in LIST_FIELDS:
        setattr(base, field_name, _merge_unique(getattr(base, field_name), getattr(incoming, field_name)))

    if incoming.open_access_status == "yes":
        base.open_access_status = "yes"
    elif base.open_access_status == "unknown" and incoming.open_access_status == "no":
        base.open_access_status = "no"

    base.fulltext_available = base.fulltext_available or incoming.fulltext_available
    if incoming.enriched_at and not base.enriched_at:
        base.enriched_at = incoming.enriched_at

    # Reclassificação é feita depois da fusão; estes campos não são mesclados aqui.
    base.ensure_identity()
    return base


def deduplicate_articles(articles: Iterable[Article]) -> list[Article]:
    merged: list[Article] = []
    key_to_index: dict[str, int] = {}

    for article in articles:
        article.ensure_identity()
        keys = identity_keys(article)
        match_index = next((key_to_index[k] for k in keys if k in key_to_index), None)

        if match_index is None:
            match_index = len(merged)
            merged.append(article)
        else:
            merge_articles(merged[match_index], article)

        # Atualize os índices após a fusão, pois uma fonte pode ter adicionado DOI/PMID.
        for key in identity_keys(merged[match_index]):
            key_to_index[key] = match_index

    return merged


def identity_keys(article: Article) -> list[str]:
    keys: list[str] = []
    if article.pmid:
        keys.append(f"pmid:{article.pmid.strip()}")
    if article.doi:
        keys.append(f"doi:{normalize_doi(article.doi)}")
    if article.pmc_id:
        keys.append(f"pmc:{article.pmc_id.strip().upper()}")

    fingerprint = title_fingerprint(article.title, article.pub_date or article.online_date)
    if fingerprint:
        keys.append(f"title:{fingerprint}")
    return keys


def title_fingerprint(title: str, date_value: str = "") -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", (title or "").casefold()).strip()
    if len(normalized) < 30:
        return ""
    year_match = re.match(r"((?:19|20)\d{2})", date_value or "")
    year = year_match.group(1) if year_match else ""
    return f"{normalized}|{year}"


def _merge_unique(existing: Iterable[str], incoming: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(existing) + list(incoming):
        value = " ".join(str(raw).split()).strip()
        if not value:
            continue
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out

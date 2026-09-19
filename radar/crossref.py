from __future__ import annotations

import html
import re
import time
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import requests

from .config import (
    CROSSREF_DISCOVERY_INCLUDE_CREATED,
    CROSSREF_EMAIL,
    CROSSREF_RETMAX,
    DISCOVERY_QUERY,
    ENRICHMENT_TIMEOUT,
    TOOL_NAME,
)
from .merge import deduplicate_articles
from .models import Article, normalize_doi

CROSSREF_BASE = "https://api.crossref.org/v1/works"


class CrossrefClient:
    """Descoberta e lookup de trabalhos via Crossref REST API."""

    def __init__(self, timeout: int = ENRICHMENT_TIMEOUT) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        agent = f"{TOOL_NAME}/1.0"
        if CROSSREF_EMAIL:
            agent += f" (mailto:{CROSSREF_EMAIL})"
        self.session.headers.update({"User-Agent": agent, "Accept": "application/json"})

    def search_recent(
        self,
        *,
        days: int,
        retmax: int = CROSSREF_RETMAX,
        query: str = DISCOVERY_QUERY,
    ) -> list[Article]:
        end = date.today()
        start = end - timedelta(days=max(days, 1) - 1)
        date_from = start.isoformat()
        date_to = end.isoformat()
        retmax = max(1, min(int(retmax), 5000))

        found: list[Article] = []
        found.extend(
            self._search_window(
                query=query,
                filter_value=(
                    f"type:journal-article,from-pub-date:{date_from},until-pub-date:{date_to}"
                ),
                retmax=retmax,
                reason="publication-date",
            )
        )

        if CROSSREF_DISCOVERY_INCLUDE_CREATED and len(found) < retmax:
            remaining = retmax - len(found)
            found.extend(
                self._search_window(
                    query=query,
                    filter_value=(
                        f"type:journal-article,from-created-date:{date_from},until-created-date:{date_to}"
                    ),
                    retmax=remaining,
                    reason="created-date",
                )
            )

        return deduplicate_articles(found)[:retmax]

    def lookup_doi(self, doi: str) -> Article | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        response = self._request(f"{CROSSREF_BASE}/{quote(normalized, safe='')}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        message = response.json().get("message") or {}
        if not isinstance(message, dict):
            return None
        return article_from_crossref_item(message, discovery_reason="doi-lookup")

    def _search_window(
        self,
        *,
        query: str,
        filter_value: str,
        retmax: int,
        reason: str,
    ) -> list[Article]:
        """Busca trabalhos no Crossref ordenados por publicação.

        Desde agosto de 2026, a API do Crossref não permite combinar
        cursor pagination com sort=published (nem com outros campos de data
        que podem estar ausentes em alguns registros). Como as buscas do Radar
        são janelas temporais pequenas e o retmax é limitado, usamos paginação
        por offset, que continua compatível com sort=published.
        """
        out: list[Article] = []
        offset = 0

        while len(out) < retmax:
            # Crossref aceita até 1000 registros por página. O Radar limita o
            # retmax a 5000, portanto offset é adequado para este caso.
            page_size = min(1000, retmax - len(out))
            params = {
                "query.bibliographic": query,
                "filter": filter_value,
                "rows": str(page_size),
                "offset": str(offset),
                "sort": "published",
                "order": "desc",
            }
            if CROSSREF_EMAIL:
                params["mailto"] = CROSSREF_EMAIL

            response = self._request(CROSSREF_BASE, params=params)
            response.raise_for_status()
            message = response.json().get("message") or {}
            items = message.get("items") or []
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                article = article_from_crossref_item(item, discovery_reason=reason)
                if article and article.title:
                    out.append(article)
                    if len(out) >= retmax:
                        break

            if len(items) < page_size:
                break

            offset += len(items)
            time.sleep(0.12)

        return out

    def _request(self, url: str, params: dict[str, str] | None = None) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = RuntimeError(f"HTTP {response.status_code}")
                    time.sleep(min(2**attempt, 12))
                    continue
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 4:
                    break
                time.sleep(min(2**attempt, 12))
        raise RuntimeError(f"Falha ao consultar Crossref: {last_error}") from last_error


def article_from_crossref_item(item: dict[str, Any], *, discovery_reason: str = "") -> Article | None:
    doi = normalize_doi(_clean(item.get("DOI")))
    title = _first_text(item.get("title"))
    if not title:
        return None

    abstract = _strip_markup(_clean(item.get("abstract")))
    journal = _first_text(item.get("container-title")) or _first_text(item.get("short-container-title"))
    online_date = _crossref_date(item.get("published-online"))
    pub_date = online_date or _crossref_date(item.get("published")) or _crossref_date(item.get("issued"))

    authors: list[str] = []
    affiliations: list[str] = []
    for author in _as_list(item.get("author")):
        if not isinstance(author, dict):
            continue
        name = " ".join(
            x for x in [_clean(author.get("given")), _clean(author.get("family"))] if x
        ).strip()
        if name:
            authors.append(name)
        for aff in _as_list(author.get("affiliation")):
            if isinstance(aff, dict):
                aff_name = _clean(aff.get("name"))
                if aff_name:
                    affiliations.append(aff_name)

    subjects = [_clean(x) for x in _as_list(item.get("subject")) if _clean(x)]
    resource = item.get("resource") or {}
    primary = resource.get("primary") or {} if isinstance(resource, dict) else {}
    publisher_url = _clean(primary.get("URL")) if isinstance(primary, dict) else ""
    publisher_url = publisher_url or _clean(item.get("URL"))

    fulltext_urls: list[str] = []
    for link in _as_list(item.get("link")):
        if isinstance(link, dict):
            url = _clean(link.get("URL"))
            if url.startswith(("http://", "https://")):
                fulltext_urls.append(url)

    source_ids = {"crossref": doi} if doi else {}
    if discovery_reason:
        source_ids["crossref_discovery"] = discovery_reason

    article = Article(
        doi=doi,
        title=title,
        abstract=abstract,
        journal=journal,
        pub_date=pub_date,
        online_date=online_date,
        authors=_merge_unique([], authors),
        publication_types=[_clean(item.get("type"))] if _clean(item.get("type")) else [],
        publisher=_clean(item.get("publisher")),
        article_type=_clean(item.get("type")),
        affiliations=_merge_unique([], affiliations),
        subjects=_merge_unique([], subjects),
        publisher_url=publisher_url,
        fulltext_urls=_merge_unique([], fulltext_urls),
        fulltext_available=bool(fulltext_urls),
        source_ids=source_ids,
        discovery_sources=["Crossref"],
    )
    return article.ensure_identity()


def merge_crossref_metadata(article: Article, item_article: Article) -> bool:
    """Aplica metadados Crossref sem apagar campos mais ricos já existentes."""
    before = article.to_dict()

    if not article.doi and item_article.doi:
        article.doi = item_article.doi
    if not article.publisher and item_article.publisher:
        article.publisher = item_article.publisher
    if not article.article_type and item_article.article_type:
        article.article_type = item_article.article_type
    if not article.publisher_url and item_article.publisher_url:
        article.publisher_url = item_article.publisher_url
    if not article.online_date and item_article.online_date:
        article.online_date = item_article.online_date
    if not article.journal and item_article.journal:
        article.journal = item_article.journal
    if len(item_article.abstract) > len(article.abstract):
        article.abstract = item_article.abstract

    article.affiliations = _merge_unique(article.affiliations, item_article.affiliations)
    article.subjects = _merge_unique(article.subjects, item_article.subjects)
    article.fulltext_urls = _merge_unique(article.fulltext_urls, item_article.fulltext_urls)
    article.fulltext_available = article.fulltext_available or item_article.fulltext_available
    article.source_ids.update(item_article.source_ids)
    article.ensure_identity()
    return before != article.to_dict()


def _crossref_date(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    parts = value.get("date-parts") or []
    if not parts or not isinstance(parts[0], list):
        return ""
    values = parts[0]
    if not values:
        return ""
    try:
        year = int(values[0])
        if len(values) == 1:
            return f"{year:04d}"
        month = int(values[1])
        if len(values) == 2:
            return f"{year:04d}-{month:02d}"
        day = int(values[2])
        return f"{year:04d}-{month:02d}-{day:02d}"
    except (TypeError, ValueError):
        return ""


def _strip_markup(value: str) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def _first_text(value: Any) -> str:
    values = _as_list(value)
    return _clean(values[0]) if values else ""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in [*existing, *incoming]:
        value = _clean(raw)
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            out.append(value)
    return out

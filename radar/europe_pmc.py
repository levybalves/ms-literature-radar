from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import requests

from .config import DISCOVERY_QUERY, ENRICHMENT_TIMEOUT, EUROPE_PMC_RETMAX, TOOL_NAME, PUBMED_EMAIL
from .models import Article, normalize_doi

EUROPE_PMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class EuropePMCClient:
    """Cliente para descoberta e enriquecimento via Europe PMC REST API."""

    def __init__(self, timeout: int = ENRICHMENT_TIMEOUT) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        agent = f"{TOOL_NAME}/1.0"
        if PUBMED_EMAIL:
            agent += f" (mailto:{PUBMED_EMAIL})"
        self.session.headers.update({"User-Agent": agent, "Accept": "application/json"})

    def search_recent(
        self,
        *,
        days: int,
        retmax: int = EUROPE_PMC_RETMAX,
        query: str = DISCOVERY_QUERY,
    ) -> list[Article]:
        end = date.today()
        start = end - timedelta(days=max(days, 1) - 1)
        retmax = max(1, min(int(retmax), 5000))
        query_text = (
            f'"{query}" AND FIRST_PDATE:[{start.isoformat()} TO {end.isoformat()}] sort_date:y'
        )

        out: list[Article] = []
        cursor = "*"
        while len(out) < retmax:
            page_size = min(250, retmax - len(out))
            params = {
                "query": query_text,
                "format": "json",
                "resultType": "core",
                "pageSize": str(page_size),
                "cursorMark": cursor,
            }
            response = self._request(EUROPE_PMC_SEARCH, params=params)
            response.raise_for_status()
            payload = response.json()
            results = ((payload.get("resultList") or {}).get("result") or [])
            if not isinstance(results, list) or not results:
                break

            for result in results:
                if isinstance(result, dict):
                    article = article_from_epmc_result(result)
                    if article and article.title:
                        out.append(article)
                        if len(out) >= retmax:
                            break

            next_cursor = payload.get("nextCursorMark")
            if len(results) < page_size or not next_cursor or next_cursor == cursor:
                break
            cursor = str(next_cursor)
            time.sleep(0.1)

        return out

    def lookup_article(self, *, pmid: str = "", doi: str = "", pmc_id: str = "") -> Article | None:
        if pmid:
            query = f"EXT_ID:{pmid} AND SRC:MED"
        elif doi:
            query = f'DOI:"{normalize_doi(doi)}"'
        elif pmc_id:
            query = f"PMCID:{pmc_id}"
        else:
            return None

        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": "1",
        }
        response = self._request(EUROPE_PMC_SEARCH, params=params)
        response.raise_for_status()
        results = ((response.json().get("resultList") or {}).get("result") or [])
        if not results or not isinstance(results[0], dict):
            return None
        return article_from_epmc_result(results[0])

    def _request(self, url: str, params: dict[str, str]) -> requests.Response:
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
        raise RuntimeError(f"Falha ao consultar Europe PMC: {last_error}") from last_error


def article_from_epmc_result(result: dict[str, Any]) -> Article | None:
    title = _clean(result.get("title"))
    if not title:
        return None

    pmid = _clean(result.get("pmid"))
    pmc_id = _clean(result.get("pmcid")).upper()
    doi = normalize_doi(_clean(result.get("doi")))
    source = _clean(result.get("source"))
    ext_id = _clean(result.get("id")) or _clean(result.get("extId")) or _clean(result.get("ext_id"))

    journal_info = result.get("journalInfo") or {}
    journal_data = journal_info.get("journal") or {} if isinstance(journal_info, dict) else {}
    journal = _clean(journal_data.get("title")) if isinstance(journal_data, dict) else ""
    journal = journal or _clean(result.get("journalTitle"))

    authors = _extract_authors(result)
    affiliations = _extract_affiliations(result)
    keywords = _extract_keyword_list(result)
    mesh_terms = _extract_mesh_terms(result)
    pub_types = [_clean(x) for x in _as_list((result.get("pubTypeList") or {}).get("pubType")) if _clean(x)]
    fulltext_urls = _extract_fulltext_urls(result)

    if pmc_id and _clean(result.get("inEPMC")).upper() == "Y":
        fulltext_urls = _merge_unique(fulltext_urls, [f"https://europepmc.org/articles/{pmc_id}/"])

    oa_raw = _clean(result.get("isOpenAccess")).upper()
    oa_status = "yes" if oa_raw == "Y" else "no" if oa_raw == "N" else "unknown"

    source_ids: dict[str, str] = {}
    if source and ext_id:
        source_ids[f"europe_pmc:{source}"] = ext_id
    elif ext_id:
        source_ids["europe_pmc"] = ext_id

    article = Article(
        pmid=pmid,
        doi=doi,
        pmc_id=pmc_id,
        source_ids=source_ids,
        discovery_sources=["Europe PMC"],
        title=title,
        abstract=_clean(result.get("abstractText")),
        journal=journal,
        pub_date=_clean(result.get("firstPublicationDate")) or _clean(result.get("electronicPublicationDate")) or _clean(result.get("printPublicationDate")) or _clean(result.get("pubYear")),
        online_date=_clean(result.get("electronicPublicationDate")) or _clean(result.get("firstPublicationDate")),
        authors=authors,
        publication_types=pub_types,
        mesh_terms=mesh_terms,
        author_keywords=keywords,
        affiliations=affiliations,
        article_type=pub_types[0] if pub_types else "",
        open_access_status=oa_status,
        fulltext_available=bool(fulltext_urls) or _clean(result.get("inEPMC")).upper() == "Y",
        fulltext_urls=fulltext_urls,
    )
    return article.ensure_identity()


def merge_epmc_metadata(article: Article, epmc_article: Article) -> bool:
    before = article.to_dict()

    if not article.pmid and epmc_article.pmid:
        article.pmid = epmc_article.pmid
    if not article.doi and epmc_article.doi:
        article.doi = epmc_article.doi
    if not article.pmc_id and epmc_article.pmc_id:
        article.pmc_id = epmc_article.pmc_id
    if not article.journal and epmc_article.journal:
        article.journal = epmc_article.journal
    if not article.pub_date and epmc_article.pub_date:
        article.pub_date = epmc_article.pub_date
    if not article.online_date and epmc_article.online_date:
        article.online_date = epmc_article.online_date
    if len(epmc_article.abstract) > len(article.abstract):
        article.abstract = epmc_article.abstract
    if not article.article_type and epmc_article.article_type:
        article.article_type = epmc_article.article_type

    article.authors = _merge_unique(article.authors, epmc_article.authors)
    article.publication_types = _merge_unique(article.publication_types, epmc_article.publication_types)
    article.mesh_terms = _merge_unique(article.mesh_terms, epmc_article.mesh_terms)
    article.author_keywords = _merge_unique(article.author_keywords, epmc_article.author_keywords)
    article.affiliations = _merge_unique(article.affiliations, epmc_article.affiliations)
    article.fulltext_urls = _merge_unique(article.fulltext_urls, epmc_article.fulltext_urls)
    article.source_ids.update(epmc_article.source_ids)
    article.fulltext_available = article.fulltext_available or epmc_article.fulltext_available

    if epmc_article.open_access_status == "yes":
        article.open_access_status = "yes"
    elif article.open_access_status == "unknown" and epmc_article.open_access_status == "no":
        article.open_access_status = "no"

    article.ensure_identity()
    return before != article.to_dict()


def _extract_authors(result: dict[str, Any]) -> list[str]:
    out: list[str] = []
    author_list = (result.get("authorList") or {}).get("author") or []
    for author in _as_list(author_list):
        if not isinstance(author, dict):
            continue
        name = _clean(author.get("fullName"))
        if not name:
            name = " ".join(x for x in [_clean(author.get("firstName")), _clean(author.get("lastName"))] if x)
        if name:
            out.append(name)
    if not out:
        author_string = _clean(result.get("authorString"))
        if author_string:
            out = [x.strip() for x in author_string.split(",") if x.strip()]
    return _merge_unique([], out)


def _extract_affiliations(result: dict[str, Any]) -> list[str]:
    affiliations: list[str] = []
    author_list = (result.get("authorList") or {}).get("author") or []
    for author in _as_list(author_list):
        if not isinstance(author, dict):
            continue
        details = (author.get("authorAffiliationDetailsList") or {}).get("authorAffiliation") or []
        for detail in _as_list(details):
            if isinstance(detail, dict):
                value = _clean(detail.get("affiliation"))
                if value:
                    affiliations.append(value)
    return _merge_unique([], affiliations)


def _extract_keyword_list(result: dict[str, Any]) -> list[str]:
    raw = (result.get("keywordList") or {}).get("keyword") or []
    return _merge_unique([], [_clean(x) for x in _as_list(raw) if _clean(x)])


def _extract_mesh_terms(result: dict[str, Any]) -> list[str]:
    out: list[str] = []
    raw = (result.get("meshHeadingList") or {}).get("meshHeading") or []
    for item in _as_list(raw):
        if isinstance(item, dict):
            descriptor = item.get("descriptorName")
            if isinstance(descriptor, dict):
                value = _clean(descriptor.get("value") or descriptor.get("name"))
            else:
                value = _clean(descriptor)
            if value:
                out.append(value)
    return _merge_unique([], out)


def _extract_fulltext_urls(result: dict[str, Any]) -> list[str]:
    raw = (result.get("fullTextUrlList") or {}).get("fullTextUrl") or []
    out: list[str] = []
    for item in _as_list(raw):
        value = _clean(item.get("url")) if isinstance(item, dict) else _clean(item)
        if value.startswith(("http://", "https://")):
            out.append(value)
    return _merge_unique([], out)


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

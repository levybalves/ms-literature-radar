from __future__ import annotations

import json
import re
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment]

from .config import (
    CROSSREF_ENABLED,
    ENRICHMENT_PAUSE_SECONDS,
    ENRICHMENT_TIMEOUT,
    EUROPE_PMC_ENABLED,
    HTML_MAX_BYTES,
    PUBMED_EMAIL,
    TOOL_NAME,
)
from .crossref import CrossrefClient, merge_crossref_metadata
from .europe_pmc import EuropePMCClient, merge_epmc_metadata
from .models import Article


@dataclass(slots=True)
class EnrichmentOutcome:
    enriched: bool = False
    sources: list[str] | None = None
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.sources is None:
            self.sources = []
        if self.errors is None:
            self.errors = []


class MetadataEnricher:
    """Complementa um registro já descoberto por qualquer fonte bibliográfica."""

    def __init__(self, *, publisher_html: bool = False, timeout: int = ENRICHMENT_TIMEOUT) -> None:
        self.publisher_html = publisher_html
        self.timeout = timeout
        self.user_agent = _user_agent()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            }
        )
        self.crossref = CrossrefClient(timeout=timeout)
        self.epmc = EuropePMCClient(timeout=timeout)

    def enrich(self, article: Article) -> EnrichmentOutcome:
        outcome = EnrichmentOutcome()

        # Se o artigo já foi descoberto pelo Crossref/Europe PMC, a maior parte
        # desses metadados já veio na descoberta; evite repetir a mesma chamada.
        if CROSSREF_ENABLED and article.doi and "Crossref" not in article.discovery_sources:
            try:
                found = self.crossref.lookup_doi(article.doi)
                changed = bool(found and merge_crossref_metadata(article, found))
                if changed:
                    outcome.sources.append("Crossref")
                    outcome.enriched = True
            except Exception as exc:
                outcome.errors.append(f"Crossref: {exc}")
            self._pause()

        if EUROPE_PMC_ENABLED and (article.pmid or article.doi or article.pmc_id) and "Europe PMC" not in article.discovery_sources:
            try:
                found = self.epmc.lookup_article(pmid=article.pmid, doi=article.doi, pmc_id=article.pmc_id)
                changed = bool(found and merge_epmc_metadata(article, found))
                if changed:
                    outcome.sources.append("Europe PMC")
                    outcome.enriched = True
            except Exception as exc:
                outcome.errors.append(f"Europe PMC: {exc}")
            self._pause()

        if self.publisher_html and (article.publisher_url or article.doi):
            try:
                changed = self._publisher_html(article)
                if changed:
                    outcome.sources.append("Publisher HTML")
                    outcome.enriched = True
            except Exception as exc:
                outcome.errors.append(f"Publisher HTML: {exc}")
            self._pause()

        if outcome.sources:
            article.enrichment_sources = _merge_unique(article.enrichment_sources, outcome.sources)
        if outcome.errors:
            article.enrichment_notes = _merge_unique(article.enrichment_notes, outcome.errors)
        if outcome.enriched:
            article.enriched_at = _utcnow()

        return outcome

    def _publisher_html(self, article: Article) -> bool:
        target_url = article.publisher_url
        if not target_url:
            return False

        host = (urlparse(target_url).hostname or "").lower()
        if host in {"doi.org", "dx.doi.org"}:
            try:
                redirect = self._request(
                    target_url,
                    allow_redirects=False,
                    stream=True,
                    headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.7"},
                    timeout=min(self.timeout, 12),
                )
                location = _clean(redirect.headers.get("Location"))
                redirect.close()
                if location:
                    target_url = urljoin(target_url, location)
                else:
                    article.enrichment_notes = _merge_unique(
                        article.enrichment_notes,
                        ["Publisher HTML ignorado: DOI não forneceu URL direta da editora"],
                    )
                    return False
            except Exception as exc:
                article.enrichment_notes = _merge_unique(
                    article.enrichment_notes,
                    [f"Publisher HTML ignorado: não foi possível resolver o DOI ({exc})"],
                )
                return False

        allowed, reason = self._robots_allows(target_url)
        if not allowed:
            if reason:
                article.enrichment_notes = _merge_unique(
                    article.enrichment_notes,
                    [f"Publisher HTML ignorado: {reason}"],
                )
            return False

        response = self._request(
            target_url,
            allow_redirects=True,
            stream=True,
            headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.7"},
        )
        if response.status_code in {401, 403, 429}:
            article.enrichment_notes = _merge_unique(
                article.enrichment_notes,
                [f"Publisher HTML indisponível (HTTP {response.status_code})"],
            )
            return False
        response.raise_for_status()
        if "html" not in (response.headers.get("Content-Type") or "").lower():
            return False

        html_text = _read_limited(response, HTML_MAX_BYTES)
        metadata = parse_publisher_html(html_text, response.url)
        if not metadata:
            return False

        changed = False
        changed |= _set_if_empty(article, "publisher_url", response.url)
        changed |= _set_if_empty(article, "publisher", metadata.get("publisher", ""))
        changed |= _set_if_empty(article, "online_date", metadata.get("online_date", ""))
        changed |= _set_if_empty(article, "article_type", metadata.get("article_type", ""))
        changed |= _set_if_empty(article, "graphical_abstract_url", metadata.get("graphical_abstract_url", ""))

        html_abstract = _clean(metadata.get("abstract", ""))
        if html_abstract and len(html_abstract) > len(article.abstract or ""):
            article.abstract = html_abstract
            changed = True

        for field_name in ["author_keywords", "affiliations", "fulltext_urls", "supplementary_urls"]:
            incoming = metadata.get(field_name) or []
            if incoming:
                current = getattr(article, field_name)
                merged = _merge_unique(current, incoming)
                if merged != current:
                    setattr(article, field_name, merged)
                    changed = True

        if metadata.get("fulltext_available") and not article.fulltext_available:
            article.fulltext_available = True
            changed = True

        status = metadata.get("open_access_status")
        if status in {"yes", "no"} and article.open_access_status == "unknown":
            article.open_access_status = status
            changed = True

        return bool(changed)

    def _robots_allows(self, target_url: str) -> tuple[bool, str]:
        parsed = urlparse(target_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False, "URL inválida"

        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = self._request(robots_url, timeout=min(self.timeout, 10))
        except Exception:
            return False, "não foi possível verificar robots.txt"

        if response.status_code == 404:
            return True, ""
        if response.status_code >= 400:
            return False, f"robots.txt retornou HTTP {response.status_code}"

        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        if parser.can_fetch(TOOL_NAME, target_url) or parser.can_fetch(self.user_agent, target_url):
            return True, ""
        return False, "bloqueado por robots.txt"

    def _request(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        stream: bool = False,
        allow_redirects: bool = True,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    stream=stream,
                    allow_redirects=allow_redirects,
                    headers=headers,
                    timeout=timeout or self.timeout,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = RuntimeError(f"HTTP {response.status_code} em {url}")
                    response.close()
                    time.sleep(min(2 ** attempt, 8))
                    continue
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 3:
                    break
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"Falha de rede ao acessar {url}: {last_error}") from last_error

    @staticmethod
    def _pause() -> None:
        if ENRICHMENT_PAUSE_SECONDS:
            time.sleep(ENRICHMENT_PAUSE_SECONDS)


def parse_publisher_html(html: str, base_url: str) -> dict[str, Any]:
    """Extrai apenas metadados públicos/genéricos; não extrai texto integral protegido."""
    if BeautifulSoup is None:
        raise RuntimeError("BeautifulSoup não está instalado; instale beautifulsoup4 para usar HTML de editoras")
    soup = BeautifulSoup(html, "html.parser")
    meta = _collect_meta(soup)
    jsonld = _find_scholarly_jsonld(soup)

    keywords: list[str] = []
    for key in ("citation_keywords", "keywords", "dc.subject", "dc.keywords"):
        for value in meta.get(key, []):
            keywords.extend(_split_keywords(value))

    if jsonld:
        keywords.extend(_split_keywords(jsonld.get("keywords")))

    affiliations: list[str] = []
    for key in ("citation_author_institution", "dc.contributor"):
        affiliations.extend(meta.get(key, []))

    publisher = _first_meta(meta, "citation_publisher", "dc.publisher")
    online_date = _first_meta(
        meta,
        "citation_online_date",
        "citation_publication_date",
        "dc.date",
        "article:published_time",
    )
    article_type = _first_meta(meta, "citation_article_type", "article:section", "og:type")
    abstract = _first_meta(
        meta,
        "citation_abstract",
        "dc.description",
        "og:description",
        "description",
    )

    if jsonld:
        publisher = publisher or _jsonld_publisher(jsonld)
        online_date = online_date or _clean(jsonld.get("datePublished"))
        article_type = article_type or _jsonld_type(jsonld)
        abstract = abstract or _clean(jsonld.get("abstract")) or _clean(jsonld.get("description"))

    fulltext_urls: list[str] = []
    for key in ("citation_fulltext_html_url", "citation_pdf_url"):
        for value in meta.get(key, []):
            fulltext_urls.append(urljoin(base_url, value))

    supplementary_urls = _supplementary_links(soup, base_url)

    graphical = _first_meta(meta, "citation_graphical_abstract")
    if graphical:
        graphical = urljoin(base_url, graphical)
    else:
        graphical = _graphical_abstract_from_html(soup, base_url)

    open_access_status = "unknown"
    if jsonld and isinstance(jsonld.get("isAccessibleForFree"), bool):
        open_access_status = "yes" if jsonld["isAccessibleForFree"] else "no"

    return {
        "publisher": _clean(publisher),
        "abstract": _clean(abstract),
        "online_date": _normalize_date(_clean(online_date)),
        "article_type": _clean(article_type),
        "author_keywords": _merge_unique([], keywords),
        "affiliations": _merge_unique([], [_clean(x) for x in affiliations if _clean(x)]),
        "fulltext_urls": _merge_unique([], fulltext_urls),
        "fulltext_available": bool(fulltext_urls),
        "supplementary_urls": supplementary_urls,
        "graphical_abstract_url": graphical,
        "open_access_status": open_access_status,
    }


def _collect_meta(soup: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for tag in soup.find_all("meta"):
        key = _clean(tag.get("name") or tag.get("property")).lower()
        value = _clean(tag.get("content"))
        if key and value:
            out.setdefault(key, []).append(value)
    return out


def _find_scholarly_jsonld(soup: Any) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        candidates.extend(_walk_jsonld(data))

    preferred = {"scholarlyarticle", "article", "medicalscholarlyarticle", "newsarticle"}
    for item in candidates:
        types = {_clean(x).lower() for x in _as_list(item.get("@type"))}
        if types & preferred:
            return item
    return candidates[0] if candidates else None


def _walk_jsonld(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        out.append(value)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in value:
                out.extend(_walk_jsonld(value[key]))
    elif isinstance(value, list):
        for item in value:
            out.extend(_walk_jsonld(item))
    return out


def _supplementary_links(soup: Any, base_url: str) -> list[str]:
    pattern = re.compile(r"supplement|supporting\s+information|supplementary\s+material", re.I)
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        text = " ".join(anchor.stripped_strings)
        href = _clean(anchor.get("href"))
        if pattern.search(text) or pattern.search(href):
            absolute = urljoin(base_url, href)
            if absolute.startswith(("http://", "https://")):
                urls.append(absolute)
        if len(urls) >= 10:
            break
    return _merge_unique([], urls)


def _graphical_abstract_from_html(soup: Any, base_url: str) -> str:
    pattern = re.compile(r"graphical\s+abstract", re.I)
    for image in soup.find_all("img", src=True):
        label = " ".join(
            filter(
                None,
                [
                    _clean(image.get("alt")),
                    _clean(image.get("title")),
                    " ".join(image.get("class") or []),
                ],
            )
        )
        if pattern.search(label):
            return urljoin(base_url, _clean(image.get("src")))
    return ""


def _extract_epmc_fulltext_urls(result: dict[str, Any]) -> list[str]:
    url_list = (result.get("fullTextUrlList") or {}).get("fullTextUrl") or []
    urls: list[str] = []
    for item in _as_list(url_list):
        if isinstance(item, dict):
            value = _clean(item.get("url"))
        else:
            value = _clean(item)
        if value.startswith(("http://", "https://")):
            urls.append(value)
    return _merge_unique([], urls)


def _extract_epmc_affiliations(result: dict[str, Any]) -> list[str]:
    affiliations: list[str] = []
    author_list = (result.get("authorList") or {}).get("author") or []
    for author in _as_list(author_list):
        if not isinstance(author, dict):
            continue
        details = (author.get("authorAffiliationDetailsList") or {}).get(
            "authorAffiliation"
        ) or []
        for detail in _as_list(details):
            if isinstance(detail, dict):
                value = _clean(detail.get("affiliation"))
                if value:
                    affiliations.append(value)
    return _merge_unique([], affiliations)


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


def _normalize_date(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"((?:19|20)\d{2})[-/]?(\d{1,2})?[-/]?(\d{1,2})?", value)
    if not match:
        return value
    year, month, day = match.groups()
    if month and day:
        return f"{year}-{int(month):02d}-{int(day):02d}"
    if month:
        return f"{year}-{int(month):02d}"
    return year


def _jsonld_publisher(data: dict[str, Any]) -> str:
    publisher = data.get("publisher")
    if isinstance(publisher, dict):
        return _clean(publisher.get("name"))
    return _clean(publisher)


def _jsonld_type(data: dict[str, Any]) -> str:
    value = data.get("@type")
    values = [_clean(x) for x in _as_list(value) if _clean(x)]
    return values[0] if values else ""


def _first_meta(meta: dict[str, list[str]], *keys: str) -> str:
    for key in keys:
        values = meta.get(key.lower()) or []
        if values:
            return _clean(values[0])
    return ""


def _split_keywords(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_split_keywords(item))
        return out
    if not isinstance(value, str):
        return []
    parts = re.split(r"[;,|]", value)
    return [_clean(part) for part in parts if _clean(part)]


def _read_limited(response: requests.Response, max_bytes: int) -> str:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        remaining = max_bytes - size
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        size += min(len(chunk), remaining)
        if size >= max_bytes:
            break
    encoding = response.encoding or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


def _set_if_empty(article: Article, field_name: str, value: str) -> bool:
    value = _clean(value)
    if not value or getattr(article, field_name):
        return False
    setattr(article, field_name, value)
    return True


def _merge_unique(existing: Iterable[str], incoming: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(existing) + list(incoming):
        value = _clean(raw)
        if not value:
            continue
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _user_agent() -> str:
    if PUBMED_EMAIL:
        return f"{TOOL_NAME}/1.0 (mailto:{PUBMED_EMAIL})"
    return f"{TOOL_NAME}/1.0 (local research tool)"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

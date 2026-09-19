from __future__ import annotations

import calendar
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Iterable

import requests

from .config import (
    BASE_QUERY,
    NCBI_API_KEY,
    PUBMED_BATCH_SIZE,
    PUBMED_EMAIL,
    PUBMED_RETMAX,
    TOOL_NAME,
)
from .models import Article

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


class PubMedClient:
    """Cliente pequeno e respeitoso para NCBI E-utilities."""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"{TOOL_NAME}/1.0 ({PUBMED_EMAIL or 'local-use'})",
                "Accept": "application/json, application/xml;q=0.9, */*;q=0.8",
            }
        )

    def _common_params(self) -> dict[str, str]:
        params = {"tool": TOOL_NAME}
        if PUBMED_EMAIL:
            params["email"] = PUBMED_EMAIL
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY
        return params

    def search(
        self,
        *,
        days: int,
        retmax: int = PUBMED_RETMAX,
        query: str = BASE_QUERY,
    ) -> list[str]:
        end = date.today()
        start = end - timedelta(days=max(days, 1) - 1)

        params = {
            **self._common_params(),
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": str(retmax),
            "sort": "pub date",
            "datetype": "pdat",
            "mindate": start.strftime("%Y/%m/%d"),
            "maxdate": end.strftime("%Y/%m/%d"),
        }
        data = self._get_json(f"{EUTILS}/esearch.fcgi", params)
        return data.get("esearchresult", {}).get("idlist", [])

    def fetch(self, pmids: Iterable[str]) -> list[Article]:
        ids = list(dict.fromkeys(str(p) for p in pmids if p))
        if not ids:
            return []

        articles: list[Article] = []
        for i in range(0, len(ids), PUBMED_BATCH_SIZE):
            chunk = ids[i : i + PUBMED_BATCH_SIZE]
            params = {
                **self._common_params(),
                "db": "pubmed",
                "id": ",".join(chunk),
                "retmode": "xml",
            }
            xml_text = self._get_text(f"{EUTILS}/efetch.fcgi", params)
            articles.extend(parse_pubmed_xml(xml_text))

            # A pipeline normalmente faz pouquíssimas requisições, mas esse intervalo
            # mantém o cliente conservador mesmo sem API key.
            if i + PUBMED_BATCH_SIZE < len(ids):
                time.sleep(0.36 if not NCBI_API_KEY else 0.12)

        return articles

    def search_and_fetch(self, *, days: int, retmax: int = PUBMED_RETMAX) -> list[Article]:
        return self.fetch(self.search(days=days, retmax=retmax))

    def _get_json(self, url: str, params: dict[str, str]) -> dict:
        response = self._request(url, params)
        return response.json()

    def _get_text(self, url: str, params: dict[str, str]) -> str:
        response = self._request(url, params)
        return response.text

    def _request(self, url: str, params: dict[str, str]) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    wait = min(2**attempt, 12)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 4:
                    break
                time.sleep(min(2**attempt, 12))
        raise RuntimeError(f"Falha ao consultar PubMed: {last_error}") from last_error


def parse_pubmed_xml(xml_text: str) -> list[Article]:
    root = ET.fromstring(xml_text)
    out: list[Article] = []

    for item in root.findall(".//PubmedArticle"):
        citation = item.find("MedlineCitation")
        article_node = item.find("MedlineCitation/Article")
        pubmed_data = item.find("PubmedData")
        if citation is None or article_node is None:
            continue

        pmid = _text(citation.find("PMID"))
        title = _node_text(article_node.find("ArticleTitle"))
        abstract = _abstract(article_node)
        journal = (
            _text(article_node.find("Journal/Title"))
            or _text(article_node.find("Journal/ISOAbbreviation"))
        )
        pub_date = _publication_date(article_node)
        authors = _authors(article_node)
        publication_types = [
            _text(x) for x in article_node.findall("PublicationTypeList/PublicationType") if _text(x)
        ]
        mesh_terms = [
            _text(x.find("DescriptorName"))
            for x in citation.findall("MeshHeadingList/MeshHeading")
            if _text(x.find("DescriptorName"))
        ]
        keywords = [
            _node_text(x)
            for x in citation.findall("KeywordList/Keyword")
            if _node_text(x)
        ]

        doi = ""
        pmc_id = ""
        if pubmed_data is not None:
            for identifier in pubmed_data.findall("ArticleIdList/ArticleId"):
                kind = (identifier.attrib.get("IdType") or "").lower()
                value = _text(identifier)
                if kind == "doi":
                    doi = value
                elif kind == "pmc":
                    pmc_id = value

        if pmid and title:
            out.append(
                Article(
                    pmid=pmid,
                    source_ids={"pubmed": pmid},
                    discovery_sources=["PubMed"],
                    title=title,
                    abstract=abstract,
                    journal=journal,
                    pub_date=pub_date,
                    authors=authors,
                    doi=doi,
                    pmc_id=pmc_id,
                    publication_types=publication_types,
                    mesh_terms=mesh_terms,
                    keywords=keywords,
                )
            )
    return out


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def _node_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _abstract(article_node: ET.Element) -> str:
    parts: list[str] = []
    for node in article_node.findall("Abstract/AbstractText"):
        body = _node_text(node)
        if not body:
            continue
        label = (node.attrib.get("Label") or "").strip()
        parts.append(f"{label}: {body}" if label else body)
    return "\n".join(parts)


def _authors(article_node: ET.Element) -> list[str]:
    out: list[str] = []
    for node in article_node.findall("AuthorList/Author"):
        collective = _text(node.find("CollectiveName"))
        if collective:
            out.append(collective)
            continue
        fore = _text(node.find("ForeName"))
        last = _text(node.find("LastName"))
        name = " ".join(x for x in [fore, last] if x)
        if name:
            out.append(name)
    return out


def _publication_date(article_node: ET.Element) -> str:
    # ArticleDate costuma representar e-publication de forma limpa.
    node = article_node.find("ArticleDate")
    if node is not None:
        year = _text(node.find("Year"))
        month = _text(node.find("Month"))
        day = _text(node.find("Day"))
        return _iso_date(year, month, day)

    node = article_node.find("Journal/JournalIssue/PubDate")
    if node is None:
        return ""

    year = _text(node.find("Year"))
    month = _text(node.find("Month"))
    day = _text(node.find("Day"))
    if year:
        return _iso_date(year, month, day)

    medline = _text(node.find("MedlineDate"))
    match = re.search(r"(19|20)\d{2}", medline)
    return match.group(0) if match else ""


def _iso_date(year: str, month: str, day: str) -> str:
    if not year:
        return ""
    if month:
        m = month.strip()
        if m.isdigit():
            month_num = max(1, min(int(m), 12))
        else:
            month_num = MONTHS.get(m[:3].lower(), 1)
        if day and day.isdigit():
            return f"{year}-{month_num:02d}-{max(1, min(int(day), 31)):02d}"
        return f"{year}-{month_num:02d}"
    return year

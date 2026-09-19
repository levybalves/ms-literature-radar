from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha1
import re
from typing import Any


def normalize_doi(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    return value.strip().lower()


def make_article_id(*, pmid: str = "", doi: str = "", pmc_id: str = "", title: str = "", pub_date: str = "") -> str:
    if pmid:
        basis = f"pmid:{pmid.strip()}"
    elif doi:
        basis = f"doi:{normalize_doi(doi)}"
    elif pmc_id:
        basis = f"pmc:{pmc_id.strip().upper()}"
    else:
        normalized_title = re.sub(r"\W+", " ", (title or "").casefold()).strip()
        basis = f"title:{normalized_title}|date:{pub_date or ''}"
    return "a_" + sha1(basis.encode("utf-8")).hexdigest()[:20]


@dataclass(slots=True)
class Article:
    # Identificador interno do Radar; independe da fonte bibliográfica.
    article_id: str = ""

    # Identificadores externos.
    pmid: str = ""
    doi: str = ""
    pmc_id: str = ""
    source_ids: dict[str, str] = field(default_factory=dict)
    discovery_sources: list[str] = field(default_factory=list)

    # Metadados bibliográficos centrais.
    title: str = ""
    abstract: str = ""
    journal: str = ""
    pub_date: str = ""
    authors: list[str] = field(default_factory=list)
    publication_types: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    # Metadados enriquecidos (Crossref / Europe PMC / HTML público da editora).
    publisher: str = ""
    online_date: str = ""
    article_type: str = ""
    affiliations: list[str] = field(default_factory=list)
    author_keywords: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    open_access_status: str = "unknown"  # yes | no | unknown
    fulltext_available: bool = False
    fulltext_urls: list[str] = field(default_factory=list)
    supplementary_urls: list[str] = field(default_factory=list)
    publisher_url: str = ""
    graphical_abstract_url: str = ""
    enrichment_sources: list[str] = field(default_factory=list)
    enrichment_notes: list[str] = field(default_factory=list)
    enriched_at: str = ""

    # Elegibilidade para o escopo de esclerose múltipla.
    # high | moderate | pending | excluded | manual | unknown
    ms_eligibility: str = "unknown"
    ms_score: float = 0.0
    ms_evidence: list[str] = field(default_factory=list)
    ms_assessed_at: str = ""

    # Classificação local.
    primary_topic: str = "general"
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_keywords: dict[str, list[str]] = field(default_factory=dict)
    relevance_score: float = 0.0

    def ensure_identity(self) -> "Article":
        self.doi = normalize_doi(self.doi)
        self.pmid = (self.pmid or "").strip()
        self.pmc_id = (self.pmc_id or "").strip().upper()
        if not self.article_id:
            self.article_id = make_article_id(
                pmid=self.pmid,
                doi=self.doi,
                pmc_id=self.pmc_id,
                title=self.title,
                pub_date=self.pub_date,
            )
        return self

    @property
    def pubmed_url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/" if self.pmid else ""

    @property
    def doi_url(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else ""

    @property
    def display_date(self) -> str:
        return self.online_date or self.pub_date

    def to_dict(self) -> dict[str, Any]:
        self.ensure_identity()
        data = asdict(self)
        data["pubmed_url"] = self.pubmed_url
        data["doi_url"] = self.doi_url
        data["display_date"] = self.display_date
        return data

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Article":
        allowed = set(cls.__dataclass_fields__)
        payload = {key: value for key, value in data.items() if key in allowed}
        return cls(**payload).ensure_identity()

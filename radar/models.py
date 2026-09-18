from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class Article:
    pmid: str
    title: str
    abstract: str = ""
    journal: str = ""
    pub_date: str = ""
    authors: list[str] = field(default_factory=list)
    doi: str = ""
    pmc_id: str = ""
    publication_types: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    primary_topic: str = "general"
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_keywords: dict[str, list[str]] = field(default_factory=dict)
    relevance_score: float = 0.0

    @property
    def pubmed_url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

    @property
    def doi_url(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pubmed_url"] = self.pubmed_url
        data["doi_url"] = self.doi_url
        return data

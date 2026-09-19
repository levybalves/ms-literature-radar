from pathlib import Path

from radar.db import Repository
from radar.eligibility import assess_ms_eligibility, apply_ms_eligibility
from radar.models import Article


def test_title_multiple_sclerosis_is_high_specificity():
    article = Article(title="Epstein-Barr virus in multiple sclerosis")
    result = assess_ms_eligibility(article)
    assert result.status == "high"
    assert result.score >= 9


def test_early_abstract_supports_article_without_ms_in_title():
    article = Article(
        title="HLA-DRB1 polymorphisms modulate peptide presentation",
        abstract=(
            "Multiple sclerosis (MS) shows a strong genetic association with HLA-DRB1 alleles. "
            "We investigated peptide presentation using molecular dynamics."
        ),
    )
    result = assess_ms_eligibility(article)
    assert result.status in {"moderate", "high"}
    assert result.score >= 6


def test_single_late_contextual_mention_is_not_enough():
    article = Article(
        title="General immune signaling in inflammatory disorders",
        abstract=("This study investigates inflammatory signaling across several unrelated conditions. " * 12)
        + "Multiple sclerosis was mentioned as one example among many diseases.",
        keywords=["inflammation"],
    )
    result = assess_ms_eligibility(article)
    assert result.status == "excluded"
    assert result.score < 6


def test_ms_acronym_alone_does_not_count():
    article = Article(
        title="MS-based mass spectrometry workflow for protein identification",
        abstract="An MS workflow was developed for analytical chemistry.",
        keywords=["mass spectrometry"],
    )
    result = assess_ms_eligibility(article)
    assert result.status == "excluded"
    assert result.score == 0


def test_sparse_crossref_candidate_remains_pending():
    article = Article(
        doi="10.1000/pending",
        title="HLA peptide presentation and autoimmunity",
        discovery_sources=["Crossref"],
    )
    result = assess_ms_eligibility(article)
    assert result.status == "pending"


def test_repository_default_feed_hides_pending_and_excluded(tmp_path: Path):
    repo = Repository(tmp_path / "radar.sqlite3")

    eligible = Article(
        doi="10.1000/eligible",
        title="Multiple sclerosis and HLA antigen presentation",
        pub_date="2026-09-19",
    )
    pending = Article(
        doi="10.1000/pending",
        title="HLA peptide presentation",
        pub_date="2026-09-19",
        discovery_sources=["Crossref"],
    )
    excluded = Article(
        doi="10.1000/excluded",
        title="Mass spectrometry in analytical chemistry",
        abstract="This work develops an MS workflow for small molecules.",
        keywords=["mass spectrometry"],
        pub_date="2026-09-19",
    )

    repo.upsert_articles([eligible, pending, excluded])

    default_feed = repo.list_articles(days=None)
    audit = repo.list_articles(days=None, ms_scope="audit")
    pending_only = repo.list_articles(days=None, ms_scope="pending")

    assert [x["doi"] for x in default_feed] == ["10.1000/eligible"]
    assert len(audit) == 3
    assert [x["doi"] for x in pending_only] == ["10.1000/pending"]


def test_manual_override_keeps_explicit_doi_import_visible():
    article = Article(
        doi="10.1000/manual",
        title="HLA peptide binding study",
        discovery_sources=["Crossref"],
    )
    apply_ms_eligibility(article, manual_override=True)
    assert article.ms_eligibility == "manual"


def test_update_pipeline_stores_eligible_and_pending_but_drops_new_excluded(tmp_path, monkeypatch):
    import radar.pipeline as pipeline

    high = Article(
        doi="10.1000/high",
        title="Multiple sclerosis and antigen presentation",
        abstract="Multiple sclerosis is the disease studied throughout this work.",
        pub_date="2026-09-19",
        discovery_sources=["Crossref"],
    )
    pending = Article(
        doi="10.1000/pending-pipeline",
        title="HLA peptide presentation and autoimmunity",
        pub_date="2026-09-19",
        discovery_sources=["Crossref"],
    )
    excluded = Article(
        doi="10.1000/noise",
        title="Proteomics workflow for inflammatory diseases",
        abstract="A mass spectrometry workflow was benchmarked across multiple sample types.",
        keywords=["mass spectrometry"],
        pub_date="2026-09-19",
        discovery_sources=["Crossref"],
    )

    monkeypatch.setattr(pipeline, "DB_PATH", tmp_path / "pipeline.sqlite3")
    monkeypatch.setattr(
        pipeline,
        "discover_literature",
        lambda days, sources=None: pipeline.DiscoveryResult(
            articles=[high, pending, excluded],
            counts={"PubMed": 0, "Crossref": 3, "Europe PMC": 0},
            successful_sources=["Crossref"],
        ),
    )

    result = pipeline.update_literature(7, enrich=False, sources={"crossref"})
    repo = Repository(tmp_path / "pipeline.sqlite3")

    assert result["ms_eligible"] == 1
    assert result["ms_pending"] == 1
    assert result["excluded_not_ms"] == 1
    assert repo.find_article(doi="10.1000/noise") is None
    assert repo.find_article(doi="10.1000/pending-pipeline") is not None
    assert [x["doi"] for x in repo.list_articles(days=None)] == ["10.1000/high"]

import sqlite3
from pathlib import Path

from radar.db import Repository
from radar.models import Article


def test_legacy_database_is_migrated(tmp_path: Path):
    db = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE articles (
            pmid TEXT PRIMARY KEY,
            doi TEXT NOT NULL DEFAULT '',
            pmc_id TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            abstract TEXT NOT NULL DEFAULT '',
            journal TEXT NOT NULL DEFAULT '',
            pub_date TEXT NOT NULL DEFAULT '',
            authors_json TEXT NOT NULL DEFAULT '[]',
            publication_types_json TEXT NOT NULL DEFAULT '[]',
            mesh_terms_json TEXT NOT NULL DEFAULT '[]',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            primary_topic TEXT NOT NULL DEFAULT 'general',
            topic_scores_json TEXT NOT NULL DEFAULT '{}',
            matched_keywords_json TEXT NOT NULL DEFAULT '{}',
            relevance_score REAL NOT NULL DEFAULT 0,
            is_favorite INTEGER NOT NULL DEFAULT 0,
            is_read INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO articles (pmid,doi,title,pub_date,first_seen_at,last_seen_at) VALUES (?,?,?,?,?,?)",
        ("999", "10.1000/legacy", "Legacy multiple sclerosis article", "2026-09-18", "x", "x"),
    )
    conn.commit()
    conn.close()

    repo = Repository(db)
    found = repo.find_article(pmid="999")
    assert found is not None
    assert found["pmid"] == "999"
    assert found["doi"] == "10.1000/legacy"
    assert found["article_id"].startswith("a_")
    assert "PubMed" in found["discovery_sources"]


def test_upsert_matches_crossref_record_when_pubmed_arrives(tmp_path: Path):
    repo = Repository(tmp_path / "radar.sqlite3")
    crossref = Article(
        doi="10.1000/same",
        title="A long title about multiple sclerosis and antigen presentation",
        pub_date="2026-09-18",
        discovery_sources=["Crossref"],
    )
    repo.upsert_articles([crossref])
    first = repo.find_article(doi="10.1000/same")

    pubmed = Article(
        pmid="12345",
        doi="10.1000/same",
        title="A long title about multiple sclerosis and antigen presentation",
        abstract="PubMed abstract",
        pub_date="2026-09-18",
        discovery_sources=["PubMed"],
    )
    inserted, updated = repo.upsert_articles([pubmed])
    second = repo.find_article(pmid="12345")

    assert inserted == 0
    assert updated == 1
    assert first["article_id"] == second["article_id"]
    assert set(second["discovery_sources"]) == {"Crossref", "PubMed"}

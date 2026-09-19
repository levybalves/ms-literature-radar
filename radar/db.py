from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .eligibility import apply_ms_eligibility
from .merge import merge_articles, title_fingerprint
from .models import Article, make_article_id, normalize_doi
from .config import MS_HIGH_THRESHOLD, MS_MODERATE_THRESHOLD, MS_REASSESS_ON_STARTUP


ARTICLE_COLUMNS = [
    "article_id", "pmid", "doi", "pmc_id", "source_ids_json", "discovery_sources_json",
    "title", "abstract", "journal", "pub_date", "authors_json", "publication_types_json",
    "mesh_terms_json", "keywords_json", "publisher", "online_date", "article_type",
    "affiliations_json", "author_keywords_json", "subjects_json", "open_access_status",
    "fulltext_available", "fulltext_urls_json", "supplementary_urls_json", "publisher_url",
    "graphical_abstract_url", "enrichment_sources_json", "enrichment_notes_json", "enriched_at",
    "ms_eligibility", "ms_score", "ms_evidence_json", "ms_assessed_at",
    "primary_topic", "topic_scores_json", "matched_keywords_json", "relevance_score",
    "is_favorite", "is_read", "first_seen_at", "last_seen_at",
]

JSON_COLUMNS = [
    "source_ids_json",
    "discovery_sources_json",
    "authors_json",
    "publication_types_json",
    "mesh_terms_json",
    "keywords_json",
    "affiliations_json",
    "author_keywords_json",
    "subjects_json",
    "fulltext_urls_json",
    "supplementary_urls_json",
    "enrichment_sources_json",
    "enrichment_notes_json",
    "ms_evidence_json",
    "topic_scores_json",
    "matched_keywords_json",
]

RUN_MIGRATIONS = {
    "enriched_count": "INTEGER NOT NULL DEFAULT 0",
    "enrichment_failures": "INTEGER NOT NULL DEFAULT 0",
    "publisher_html_count": "INTEGER NOT NULL DEFAULT 0",
    "pubmed_seen": "INTEGER NOT NULL DEFAULT 0",
    "crossref_seen": "INTEGER NOT NULL DEFAULT 0",
    "europe_pmc_seen": "INTEGER NOT NULL DEFAULT 0",
    "deduplicated_count": "INTEGER NOT NULL DEFAULT 0",
    "ms_high_count": "INTEGER NOT NULL DEFAULT 0",
    "ms_moderate_count": "INTEGER NOT NULL DEFAULT 0",
    "ms_pending_count": "INTEGER NOT NULL DEFAULT 0",
    "ms_excluded_count": "INTEGER NOT NULL DEFAULT 0",
    "discovery_errors_json": "TEXT NOT NULL DEFAULT '[]'",
}


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            # WAL é rápido em disco Linux; DELETE é mais tolerante em /mnt/c no WSL.
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                conn.execute("PRAGMA journal_mode=DELETE")

            if not _table_exists(conn, "articles"):
                _create_articles_table(conn)
            else:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()}
                if "article_id" not in cols:
                    _migrate_legacy_articles(conn)
                else:
                    _ensure_article_columns(conn)

            _create_article_indexes(conn)
            _create_runs_table(conn)
            _ensure_columns(conn, "runs", RUN_MIGRATIONS)
            if MS_REASSESS_ON_STARTUP:
                _backfill_ms_eligibility(conn)

    def upsert_articles(self, articles: Iterable[Article]) -> tuple[int, int]:
        inserted = 0
        updated = 0
        now = _utcnow()

        with self.connect() as conn:
            for incoming in articles:
                incoming.ensure_identity()
                if incoming.ms_eligibility == "unknown" or not incoming.ms_assessed_at:
                    apply_ms_eligibility(
                        incoming,
                        high_threshold=MS_HIGH_THRESHOLD,
                        moderate_threshold=MS_MODERATE_THRESHOLD,
                    )
                existing_row = _find_existing_row(conn, incoming)

                if existing_row:
                    existing = Article.from_mapping(_decode_row(existing_row))
                    favorite = int(existing_row["is_favorite"])
                    read = int(existing_row["is_read"])
                    first_seen = existing_row["first_seen_at"]

                    merged = merge_articles(existing, incoming)
                    merged.article_id = existing.article_id
                    # A classificação deve refletir o registro recém-processado.
                    if incoming.ms_assessed_at:
                        merged.ms_eligibility = incoming.ms_eligibility
                        merged.ms_score = incoming.ms_score
                        merged.ms_evidence = incoming.ms_evidence
                        merged.ms_assessed_at = incoming.ms_assessed_at
                    if incoming.topic_scores:
                        merged.primary_topic = incoming.primary_topic
                        merged.topic_scores = incoming.topic_scores
                        merged.matched_keywords = incoming.matched_keywords
                        merged.relevance_score = incoming.relevance_score

                    _update_article(conn, merged, favorite=favorite, read=read, first_seen_at=first_seen, last_seen_at=now)
                    incoming.article_id = merged.article_id
                    updated += 1
                else:
                    _insert_article(conn, incoming, favorite=0, read=0, first_seen_at=now, last_seen_at=now)
                    inserted += 1

        return inserted, updated

    def list_articles(
        self,
        *,
        topic: str = "",
        search: str = "",
        source: str = "",
        favorites_only: bool = False,
        unread_only: bool = False,
        open_access_only: bool = False,
        enriched_only: bool = False,
        ms_scope: str = "eligible",
        days: int | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []

        period_clause, period_params = _period_filter(days)
        if period_clause:
            clauses.append(period_clause)
            params.extend(period_params)

        ms_clause, ms_params = _ms_scope_filter(ms_scope)
        if ms_clause:
            clauses.append(ms_clause)
            params.extend(ms_params)

        if topic:
            clauses.append("primary_topic = ?")
            params.append(topic)

        if source:
            clauses.append("discovery_sources_json LIKE ?")
            params.append(f'%"{source}"%')

        if search:
            clauses.append(
                "(title LIKE ? OR abstract LIKE ? OR journal LIKE ? OR publisher LIKE ? "
                "OR article_type LIKE ? OR affiliations_json LIKE ? OR author_keywords_json LIKE ? "
                "OR subjects_json LIKE ? OR doi LIKE ? OR pmid LIKE ?)"
            )
            term = f"%{search}%"
            params.extend([term] * 10)

        if favorites_only:
            clauses.append("is_favorite = 1")
        if unread_only:
            clauses.append("is_read = 0")
        if open_access_only:
            clauses.append("open_access_status = 'yes'")
        if enriched_only:
            clauses.append("enriched_at <> ''")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(limit, 10000)))

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM articles
                {where}
                ORDER BY COALESCE(NULLIF(online_date, ''), pub_date) DESC,
                         relevance_score DESC,
                         first_seen_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def get_article(self, article_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM articles WHERE article_id = ?", (article_id,)).fetchone()
        return _decode_row(row) if row else None

    def find_article(self, *, pmid: str = "", doi: str = "", pmc_id: str = "") -> dict | None:
        dummy = Article(pmid=pmid, doi=doi, pmc_id=pmc_id, title="lookup").ensure_identity()
        with self.connect() as conn:
            row = _find_existing_row(conn, dummy, allow_title=False)
        return _decode_row(row) if row else None

    def stats(self, *, days: int | None = None, ms_scope: str = "eligible") -> dict:
        period_clause, period_params = _period_filter(days)
        ms_clause, ms_params = _ms_scope_filter(ms_scope)
        base_clauses = [x for x in (period_clause, ms_clause) if x]
        base_params = [*period_params, *ms_params]
        base_clause = " AND ".join(base_clauses)
        where = f"WHERE {base_clause}" if base_clause else ""

        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM articles {where}", base_params).fetchone()[0]
            favorites = _count_with_extra(conn, base_clause, base_params, "is_favorite = 1")
            unread = _count_with_extra(conn, base_clause, base_params, "is_read = 0")
            open_access = _count_with_extra(conn, base_clause, base_params, "open_access_status = 'yes'")
            enriched = _count_with_extra(conn, base_clause, base_params, "enriched_at <> ''")

            by_topic = conn.execute(
                f"SELECT primary_topic, COUNT(*) AS n FROM articles {where} GROUP BY primary_topic ORDER BY n DESC",
                base_params,
            ).fetchall()

            by_source = {}
            for source in ("PubMed", "Crossref", "Europe PMC"):
                extra = "discovery_sources_json LIKE ?"
                count_where = f"WHERE {base_clause} AND {extra}" if base_clause else f"WHERE {extra}"
                args = [*base_params, f'%"{source}"%']
                by_source[source] = conn.execute(f"SELECT COUNT(*) FROM articles {count_where}", args).fetchone()[0]

            eligible_clause, eligible_params = _ms_scope_filter("eligible")
            all_time_total = conn.execute(
                f"SELECT COUNT(*) FROM articles WHERE {eligible_clause}", eligible_params
            ).fetchone()[0]
            database_total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            eligibility_where = f"WHERE {period_clause}" if period_clause else ""
            by_eligibility_rows = conn.execute(
                f"SELECT ms_eligibility, COUNT(*) AS n FROM articles {eligibility_where} GROUP BY ms_eligibility",
                period_params,
            ).fetchall()
            last_run = conn.execute(
                "SELECT * FROM runs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
            ).fetchone()

        last_run_dict = dict(last_run) if last_run else None
        if last_run_dict:
            try:
                last_run_dict["discovery_errors"] = json.loads(last_run_dict.pop("discovery_errors_json") or "[]")
            except (json.JSONDecodeError, TypeError):
                last_run_dict["discovery_errors"] = []

        return {
            "total": total,
            "all_time_total": all_time_total,
            "database_total": database_total,
            "favorites": favorites,
            "unread": unread,
            "open_access": open_access,
            "enriched": enriched,
            "by_topic": {row["primary_topic"]: row["n"] for row in by_topic},
            "by_source": by_source,
            "by_eligibility": {row["ms_eligibility"]: row["n"] for row in by_eligibility_rows},
            "last_run": last_run_dict,
        }

    def reassess_ms_eligibility(self) -> dict[str, int]:
        counts = {"high": 0, "moderate": 0, "pending": 0, "excluded": 0, "manual": 0}
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM articles").fetchall()
            for row in rows:
                article = Article.from_mapping(_decode_row(row))
                previous = article.ms_eligibility
                apply_ms_eligibility(
                    article,
                    high_threshold=MS_HIGH_THRESHOLD,
                    moderate_threshold=MS_MODERATE_THRESHOLD,
                    manual_override=(previous == "manual"),
                )
                counts[article.ms_eligibility] = counts.get(article.ms_eligibility, 0) + 1
                conn.execute(
                    "UPDATE articles SET ms_eligibility=?, ms_score=?, ms_evidence_json=?, ms_assessed_at=? WHERE article_id=?",
                    (article.ms_eligibility, article.ms_score, _json(article.ms_evidence), article.ms_assessed_at, article.article_id),
                )
        return counts

    def toggle_flag(self, article_id: str, field: str) -> bool:
        if field not in {"is_favorite", "is_read"}:
            raise ValueError("Campo inválido")
        with self.connect() as conn:
            row = conn.execute(f"SELECT {field} FROM articles WHERE article_id = ?", (article_id,)).fetchone()
            if not row:
                raise KeyError(article_id)
            new_value = 0 if row[field] else 1
            conn.execute(f"UPDATE articles SET {field} = ? WHERE article_id = ?", (new_value, article_id))
        return bool(new_value)

    def start_run(self, query: str, days: int) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status, query, days) VALUES (?, 'running', ?, ?)",
                (_utcnow(), query, days),
            )
            return int(cur.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        articles_seen: int = 0,
        inserted: int = 0,
        updated: int = 0,
        enriched_count: int = 0,
        enrichment_failures: int = 0,
        publisher_html_count: int = 0,
        pubmed_seen: int = 0,
        crossref_seen: int = 0,
        europe_pmc_seen: int = 0,
        deduplicated_count: int = 0,
        ms_high_count: int = 0,
        ms_moderate_count: int = 0,
        ms_pending_count: int = 0,
        ms_excluded_count: int = 0,
        discovery_errors: list[str] | None = None,
        error: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET finished_at=?, status=?, articles_seen=?, inserted=?, updated=?,
                    enriched_count=?, enrichment_failures=?, publisher_html_count=?,
                    pubmed_seen=?, crossref_seen=?, europe_pmc_seen=?, deduplicated_count=?,
                    ms_high_count=?, ms_moderate_count=?, ms_pending_count=?, ms_excluded_count=?,
                    discovery_errors_json=?, error=?
                WHERE id=?
                """,
                (
                    _utcnow(), status, articles_seen, inserted, updated,
                    enriched_count, enrichment_failures, publisher_html_count,
                    pubmed_seen, crossref_seen, europe_pmc_seen, deduplicated_count,
                    ms_high_count, ms_moderate_count, ms_pending_count, ms_excluded_count,
                    _json(discovery_errors or []), error[:3000], run_id,
                ),
            )


def _create_articles_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            article_id TEXT PRIMARY KEY,
            pmid TEXT NOT NULL DEFAULT '',
            doi TEXT NOT NULL DEFAULT '',
            pmc_id TEXT NOT NULL DEFAULT '',
            source_ids_json TEXT NOT NULL DEFAULT '{}',
            discovery_sources_json TEXT NOT NULL DEFAULT '[]',
            title TEXT NOT NULL,
            abstract TEXT NOT NULL DEFAULT '',
            journal TEXT NOT NULL DEFAULT '',
            pub_date TEXT NOT NULL DEFAULT '',
            authors_json TEXT NOT NULL DEFAULT '[]',
            publication_types_json TEXT NOT NULL DEFAULT '[]',
            mesh_terms_json TEXT NOT NULL DEFAULT '[]',
            keywords_json TEXT NOT NULL DEFAULT '[]',
            publisher TEXT NOT NULL DEFAULT '',
            online_date TEXT NOT NULL DEFAULT '',
            article_type TEXT NOT NULL DEFAULT '',
            affiliations_json TEXT NOT NULL DEFAULT '[]',
            author_keywords_json TEXT NOT NULL DEFAULT '[]',
            subjects_json TEXT NOT NULL DEFAULT '[]',
            open_access_status TEXT NOT NULL DEFAULT 'unknown',
            fulltext_available INTEGER NOT NULL DEFAULT 0,
            fulltext_urls_json TEXT NOT NULL DEFAULT '[]',
            supplementary_urls_json TEXT NOT NULL DEFAULT '[]',
            publisher_url TEXT NOT NULL DEFAULT '',
            graphical_abstract_url TEXT NOT NULL DEFAULT '',
            enrichment_sources_json TEXT NOT NULL DEFAULT '[]',
            enrichment_notes_json TEXT NOT NULL DEFAULT '[]',
            enriched_at TEXT NOT NULL DEFAULT '',
            ms_eligibility TEXT NOT NULL DEFAULT 'unknown',
            ms_score REAL NOT NULL DEFAULT 0,
            ms_evidence_json TEXT NOT NULL DEFAULT '[]',
            ms_assessed_at TEXT NOT NULL DEFAULT '',
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


def _ensure_article_columns(conn: sqlite3.Connection) -> None:
    expected = {
        "source_ids_json": "TEXT NOT NULL DEFAULT '{}'",
        "discovery_sources_json": "TEXT NOT NULL DEFAULT '[]'",
        "ms_eligibility": "TEXT NOT NULL DEFAULT 'unknown'",
        "ms_score": "REAL NOT NULL DEFAULT 0",
        "ms_evidence_json": "TEXT NOT NULL DEFAULT '[]'",
        "ms_assessed_at": "TEXT NOT NULL DEFAULT ''",
    }
    _ensure_columns(conn, "articles", expected)


def _create_article_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(pub_date DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_online_date ON articles(online_date DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_score ON articles(relevance_score DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles(primary_topic)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_doi ON articles(doi)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_pmid ON articles(pmid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_pmc ON articles(pmc_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_oa ON articles(open_access_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_ms_eligibility ON articles(ms_eligibility)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_ms_score ON articles(ms_score DESC)")


def _create_runs_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            query TEXT NOT NULL,
            days INTEGER NOT NULL,
            articles_seen INTEGER NOT NULL DEFAULT 0,
            inserted INTEGER NOT NULL DEFAULT 0,
            updated INTEGER NOT NULL DEFAULT 0,
            enriched_count INTEGER NOT NULL DEFAULT 0,
            enrichment_failures INTEGER NOT NULL DEFAULT 0,
            publisher_html_count INTEGER NOT NULL DEFAULT 0,
            pubmed_seen INTEGER NOT NULL DEFAULT 0,
            crossref_seen INTEGER NOT NULL DEFAULT 0,
            europe_pmc_seen INTEGER NOT NULL DEFAULT 0,
            deduplicated_count INTEGER NOT NULL DEFAULT 0,
            ms_high_count INTEGER NOT NULL DEFAULT 0,
            ms_moderate_count INTEGER NOT NULL DEFAULT 0,
            ms_pending_count INTEGER NOT NULL DEFAULT 0,
            ms_excluded_count INTEGER NOT NULL DEFAULT 0,
            discovery_errors_json TEXT NOT NULL DEFAULT '[]',
            error TEXT NOT NULL DEFAULT ''
        )
        """
    )


def _migrate_legacy_articles(conn: sqlite3.Connection) -> None:
    rows = [dict(row) for row in conn.execute("SELECT * FROM articles").fetchall()]
    conn.execute("ALTER TABLE articles RENAME TO articles_legacy")
    _create_articles_table(conn)

    now = _utcnow()
    for row in rows:
        pmid = str(row.get("pmid") or "").strip()
        doi = normalize_doi(str(row.get("doi") or ""))
        pmc_id = str(row.get("pmc_id") or "").strip().upper()
        article_id = make_article_id(
            pmid=pmid,
            doi=doi,
            pmc_id=pmc_id,
            title=str(row.get("title") or ""),
            pub_date=str(row.get("pub_date") or ""),
        )
        source_ids = {"pubmed": pmid} if pmid else ({"doi": doi} if doi else {})
        discovery_sources = ["PubMed"] if pmid else []

        payload = {col: _legacy_default(col) for col in ARTICLE_COLUMNS}
        for col in ARTICLE_COLUMNS:
            if col in row:
                payload[col] = row[col]
        payload.update(
            {
                "article_id": article_id,
                "pmid": pmid,
                "doi": doi,
                "pmc_id": pmc_id,
                "source_ids_json": _json(source_ids),
                "discovery_sources_json": _json(discovery_sources),
                "first_seen_at": row.get("first_seen_at") or now,
                "last_seen_at": row.get("last_seen_at") or now,
            }
        )
        placeholders = ",".join("?" for _ in ARTICLE_COLUMNS)
        conn.execute(
            f"INSERT INTO articles ({','.join(ARTICLE_COLUMNS)}) VALUES ({placeholders})",
            [payload[c] for c in ARTICLE_COLUMNS],
        )

    conn.execute("DROP TABLE articles_legacy")


def _legacy_default(column: str):
    if column in {"source_ids_json", "topic_scores_json", "matched_keywords_json"}:
        return "{}"
    if column.endswith("_json"):
        return "[]"
    if column in {"fulltext_available", "is_favorite", "is_read"}:
        return 0
    if column in {"relevance_score", "ms_score"}:
        return 0.0
    if column == "ms_eligibility":
        return "unknown"
    if column == "open_access_status":
        return "unknown"
    return ""


def _find_existing_row(conn: sqlite3.Connection, article: Article, *, allow_title: bool = True) -> sqlite3.Row | None:
    if article.pmid:
        row = conn.execute("SELECT * FROM articles WHERE pmid = ? LIMIT 1", (article.pmid,)).fetchone()
        if row:
            return row
    if article.doi:
        row = conn.execute("SELECT * FROM articles WHERE doi = ? LIMIT 1", (normalize_doi(article.doi),)).fetchone()
        if row:
            return row
    if article.pmc_id:
        row = conn.execute("SELECT * FROM articles WHERE pmc_id = ? LIMIT 1", (article.pmc_id.upper(),)).fetchone()
        if row:
            return row
    if article.article_id:
        row = conn.execute("SELECT * FROM articles WHERE article_id = ? LIMIT 1", (article.article_id,)).fetchone()
        if row:
            return row

    if allow_title:
        fingerprint = title_fingerprint(article.title, article.pub_date or article.online_date)
        if fingerprint:
            year = (article.pub_date or article.online_date)[:4]
            candidates = conn.execute(
                "SELECT * FROM articles WHERE lower(title) = lower(?) OR (substr(COALESCE(NULLIF(online_date,''), pub_date),1,4)=? AND length(title)>25)",
                (article.title, year),
            ).fetchall()
            for candidate in candidates:
                decoded = _decode_row(candidate)
                if title_fingerprint(decoded.get("title", ""), decoded.get("pub_date", "") or decoded.get("online_date", "")) == fingerprint:
                    return candidate
    return None


def _article_values(article: Article, *, favorite: int, read: int, first_seen_at: str, last_seen_at: str) -> dict:
    article.ensure_identity()
    return {
        "article_id": article.article_id,
        "pmid": article.pmid,
        "doi": normalize_doi(article.doi),
        "pmc_id": article.pmc_id,
        "source_ids_json": _json(article.source_ids),
        "discovery_sources_json": _json(article.discovery_sources),
        "title": article.title,
        "abstract": article.abstract,
        "journal": article.journal,
        "pub_date": article.pub_date,
        "authors_json": _json(article.authors),
        "publication_types_json": _json(article.publication_types),
        "mesh_terms_json": _json(article.mesh_terms),
        "keywords_json": _json(article.keywords),
        "publisher": article.publisher,
        "online_date": article.online_date,
        "article_type": article.article_type,
        "affiliations_json": _json(article.affiliations),
        "author_keywords_json": _json(article.author_keywords),
        "subjects_json": _json(article.subjects),
        "open_access_status": article.open_access_status,
        "fulltext_available": int(article.fulltext_available),
        "fulltext_urls_json": _json(article.fulltext_urls),
        "supplementary_urls_json": _json(article.supplementary_urls),
        "publisher_url": article.publisher_url,
        "graphical_abstract_url": article.graphical_abstract_url,
        "enrichment_sources_json": _json(article.enrichment_sources),
        "enrichment_notes_json": _json(article.enrichment_notes),
        "enriched_at": article.enriched_at,
        "ms_eligibility": article.ms_eligibility,
        "ms_score": article.ms_score,
        "ms_evidence_json": _json(article.ms_evidence),
        "ms_assessed_at": article.ms_assessed_at,
        "primary_topic": article.primary_topic,
        "topic_scores_json": _json(article.topic_scores),
        "matched_keywords_json": _json(article.matched_keywords),
        "relevance_score": article.relevance_score,
        "is_favorite": favorite,
        "is_read": read,
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
    }


def _insert_article(conn: sqlite3.Connection, article: Article, *, favorite: int, read: int, first_seen_at: str, last_seen_at: str) -> None:
    values = _article_values(article, favorite=favorite, read=read, first_seen_at=first_seen_at, last_seen_at=last_seen_at)
    placeholders = ",".join("?" for _ in ARTICLE_COLUMNS)
    conn.execute(
        f"INSERT INTO articles ({','.join(ARTICLE_COLUMNS)}) VALUES ({placeholders})",
        [values[c] for c in ARTICLE_COLUMNS],
    )


def _update_article(conn: sqlite3.Connection, article: Article, *, favorite: int, read: int, first_seen_at: str, last_seen_at: str) -> None:
    values = _article_values(article, favorite=favorite, read=read, first_seen_at=first_seen_at, last_seen_at=last_seen_at)
    assignments = ",".join(f"{c}=?" for c in ARTICLE_COLUMNS if c != "article_id")
    params = [values[c] for c in ARTICLE_COLUMNS if c != "article_id"] + [article.article_id]
    conn.execute(f"UPDATE articles SET {assignments} WHERE article_id=?", params)


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for column, definition in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _count_with_extra(conn: sqlite3.Connection, period_clause: str, period_params: list[object], extra_clause: str) -> int:
    where = f"WHERE {period_clause} AND {extra_clause}" if period_clause else f"WHERE {extra_clause}"
    return conn.execute(f"SELECT COUNT(*) FROM articles {where}", period_params).fetchone()[0]


def _ms_scope_filter(scope: str) -> tuple[str, list[object]]:
    normalized = (scope or "eligible").strip().lower()
    if normalized in {"all", "audit"}:
        return "", []
    if normalized == "high":
        return "ms_eligibility = ?", ["high"]
    if normalized == "moderate":
        return "ms_eligibility = ?", ["moderate"]
    if normalized == "pending":
        return "ms_eligibility = ?", ["pending"]
    if normalized == "excluded":
        return "ms_eligibility = ?", ["excluded"]
    if normalized == "manual":
        return "ms_eligibility = ?", ["manual"]
    return "ms_eligibility IN ('high','moderate','manual')", []


def _backfill_ms_eligibility(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT * FROM articles WHERE ms_eligibility='unknown' OR ms_assessed_at=''"
    ).fetchall()
    for row in rows:
        article = Article.from_mapping(_decode_row(row))
        apply_ms_eligibility(
            article,
            high_threshold=MS_HIGH_THRESHOLD,
            moderate_threshold=MS_MODERATE_THRESHOLD,
        )
        conn.execute(
            "UPDATE articles SET ms_eligibility=?, ms_score=?, ms_evidence_json=?, ms_assessed_at=? WHERE article_id=?",
            (article.ms_eligibility, article.ms_score, _json(article.ms_evidence), article.ms_assessed_at, article.article_id),
        )


def _period_filter(days: int | None) -> tuple[str, list[object]]:
    """Últimos N dias de calendário, incluindo hoje, usando data online quando disponível."""
    if days is None:
        return "", []
    safe_days = max(1, min(int(days), 3650))
    cutoff = date.today() - timedelta(days=safe_days - 1)
    return "COALESCE(NULLIF(online_date, ''), pub_date) >= ?", [cutoff.isoformat()]


def _decode_row(row: sqlite3.Row | dict) -> dict:
    data = dict(row)
    for col in JSON_COLUMNS:
        raw = data.pop(col, "{}" if col in {"source_ids_json", "topic_scores_json", "matched_keywords_json"} else "[]")
        default = {} if col in {"source_ids_json", "topic_scores_json", "matched_keywords_json"} else []
        try:
            data[col[:-5]] = json.loads(raw or json.dumps(default))
        except (json.JSONDecodeError, TypeError):
            data[col[:-5]] = default

    data["is_favorite"] = bool(data.get("is_favorite", 0))
    data["is_read"] = bool(data.get("is_read", 0))
    data["fulltext_available"] = bool(data.get("fulltext_available", 0))
    data["pubmed_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{data['pmid']}/" if data.get("pmid") else ""
    data["doi_url"] = f"https://doi.org/{data['doi']}" if data.get("doi") else ""
    data["display_date"] = data.get("online_date") or data.get("pub_date") or ""
    return data


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

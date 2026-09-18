from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import Article


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS articles (
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
);

CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(pub_date DESC);
CREATE INDEX IF NOT EXISTS idx_articles_score ON articles(relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles(primary_topic);

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
    error TEXT NOT NULL DEFAULT ''
);
"""


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def upsert_articles(self, articles: Iterable[Article]) -> tuple[int, int]:
        inserted = 0
        updated = 0
        now = _utcnow()

        with self.connect() as conn:
            for a in articles:
                exists = conn.execute(
                    "SELECT 1 FROM articles WHERE pmid = ?", (a.pmid,)
                ).fetchone()
                if exists:
                    updated += 1
                else:
                    inserted += 1

                conn.execute(
                    """
                    INSERT INTO articles (
                        pmid, doi, pmc_id, title, abstract, journal, pub_date,
                        authors_json, publication_types_json, mesh_terms_json, keywords_json,
                        primary_topic, topic_scores_json, matched_keywords_json,
                        relevance_score, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(pmid) DO UPDATE SET
                        doi=excluded.doi,
                        pmc_id=excluded.pmc_id,
                        title=excluded.title,
                        abstract=excluded.abstract,
                        journal=excluded.journal,
                        pub_date=excluded.pub_date,
                        authors_json=excluded.authors_json,
                        publication_types_json=excluded.publication_types_json,
                        mesh_terms_json=excluded.mesh_terms_json,
                        keywords_json=excluded.keywords_json,
                        primary_topic=excluded.primary_topic,
                        topic_scores_json=excluded.topic_scores_json,
                        matched_keywords_json=excluded.matched_keywords_json,
                        relevance_score=excluded.relevance_score,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        a.pmid,
                        a.doi,
                        a.pmc_id,
                        a.title,
                        a.abstract,
                        a.journal,
                        a.pub_date,
                        _json(a.authors),
                        _json(a.publication_types),
                        _json(a.mesh_terms),
                        _json(a.keywords),
                        a.primary_topic,
                        _json(a.topic_scores),
                        _json(a.matched_keywords),
                        a.relevance_score,
                        now,
                        now,
                    ),
                )
        return inserted, updated

    def list_articles(
        self,
        *,
        topic: str = "",
        search: str = "",
        favorites_only: bool = False,
        unread_only: bool = False,
        days: int | None = None,
        limit: int = 500,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []

        period_clause, period_params = _period_filter(days)
        if period_clause:
            clauses.append(period_clause)
            params.extend(period_params)

        if topic:
            clauses.append("primary_topic = ?")
            params.append(topic)

        if search:
            clauses.append("(title LIKE ? OR abstract LIKE ? OR journal LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term, term])

        if favorites_only:
            clauses.append("is_favorite = 1")

        if unread_only:
            clauses.append("is_read = 0")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(limit, 5000)))

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM articles
                {where}
                ORDER BY pub_date DESC, relevance_score DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [_decode_row(row) for row in rows]

    def stats(self, *, days: int | None = None) -> dict:
        """Estatísticas do período selecionado e total histórico do banco."""
        period_clause, period_params = _period_filter(days)
        where = f"WHERE {period_clause}" if period_clause else ""

        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM articles {where}", period_params
            ).fetchone()[0]

            favorites_where = (
                f"WHERE {period_clause} AND is_favorite = 1"
                if period_clause
                else "WHERE is_favorite = 1"
            )
            favorites = conn.execute(
                f"SELECT COUNT(*) FROM articles {favorites_where}", period_params
            ).fetchone()[0]

            unread_where = (
                f"WHERE {period_clause} AND is_read = 0"
                if period_clause
                else "WHERE is_read = 0"
            )
            unread = conn.execute(
                f"SELECT COUNT(*) FROM articles {unread_where}", period_params
            ).fetchone()[0]

            by_topic = conn.execute(
                f"""
                SELECT primary_topic, COUNT(*) AS n
                FROM articles
                {where}
                GROUP BY primary_topic
                ORDER BY n DESC
                """,
                period_params,
            ).fetchall()

            all_time_total = conn.execute(
                "SELECT COUNT(*) FROM articles"
            ).fetchone()[0]

            last_run = conn.execute(
                """
                SELECT * FROM runs
                WHERE status = 'success'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        return {
            "total": total,
            "all_time_total": all_time_total,
            "favorites": favorites,
            "unread": unread,
            "by_topic": {row["primary_topic"]: row["n"] for row in by_topic},
            "last_run": dict(last_run) if last_run else None,
        }

    def toggle_flag(self, pmid: str, field: str) -> bool:
        if field not in {"is_favorite", "is_read"}:
            raise ValueError("Campo inválido")

        with self.connect() as conn:
            row = conn.execute(
                f"SELECT {field} FROM articles WHERE pmid = ?", (pmid,)
            ).fetchone()
            if not row:
                raise KeyError(pmid)

            new_value = 0 if row[field] else 1
            conn.execute(
                f"UPDATE articles SET {field} = ? WHERE pmid = ?",
                (new_value, pmid),
            )

        return bool(new_value)

    def start_run(self, query: str, days: int) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (started_at, status, query, days)
                VALUES (?, 'running', ?, ?)
                """,
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
        error: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET finished_at=?, status=?, articles_seen=?, inserted=?, updated=?, error=?
                WHERE id=?
                """,
                (
                    _utcnow(),
                    status,
                    articles_seen,
                    inserted,
                    updated,
                    error[:2000],
                    run_id,
                ),
            )


def _period_filter(days: int | None) -> tuple[str, list[object]]:
    """
    Retorna o filtro SQL para os últimos N dias de calendário, incluindo hoje.

    Ex.: days=5 inclui hoje + os quatro dias anteriores.
    Datas incompletas do PubMed (somente ano/mês) não são forçadas para um dia
    artificial, portanto podem ficar fora de janelas curtas quando o dia é desconhecido.
    """
    if days is None:
        return "", []

    safe_days = max(1, min(int(days), 3650))
    cutoff = date.today() - timedelta(days=safe_days - 1)
    return "pub_date >= ?", [cutoff.isoformat()]


def _decode_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    for col in [
        "authors_json",
        "publication_types_json",
        "mesh_terms_json",
        "keywords_json",
        "topic_scores_json",
        "matched_keywords_json",
    ]:
        data[col[:-5]] = json.loads(data.pop(col) or "[]")

    data["is_favorite"] = bool(data["is_favorite"])
    data["is_read"] = bool(data["is_read"])
    data["pubmed_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{data['pmid']}/"
    data["doi_url"] = f"https://doi.org/{data['doi']}" if data["doi"] else ""
    return data


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

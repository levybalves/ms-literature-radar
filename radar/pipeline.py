from __future__ import annotations

from .classifier import classify, load_topics
from .config import BASE_QUERY, DB_PATH, LOOKBACK_DAYS, TOPICS_PATH
from .db import Repository
from .pubmed import PubMedClient


def update_literature(days: int = LOOKBACK_DAYS) -> dict:
    repo = Repository(DB_PATH)
    run_id = repo.start_run(BASE_QUERY, days)

    try:
        topics = load_topics(TOPICS_PATH)
        client = PubMedClient()
        articles = client.search_and_fetch(days=days)
        for article in articles:
            classify(article, topics)

        inserted, updated = repo.upsert_articles(articles)
        repo.finish_run(
            run_id,
            status="success",
            articles_seen=len(articles),
            inserted=inserted,
            updated=updated,
        )
        return {
            "ok": True,
            "articles_seen": len(articles),
            "inserted": inserted,
            "updated": updated,
        }
    except Exception as exc:
        repo.finish_run(run_id, status="error", error=str(exc))
        raise

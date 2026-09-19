from datetime import date, timedelta
from pathlib import Path

from radar.db import Repository
from radar.models import Article


def test_period_filter_uses_online_date_when_available(tmp_path: Path):
    repo = Repository(tmp_path / "radar.sqlite3")
    today = date.today()
    articles = [
        Article(
            doi="10.1000/new",
            title="A long recent multiple sclerosis article for filtering",
            pub_date=(today - timedelta(days=30)).isoformat(),
            online_date=today.isoformat(),
            discovery_sources=["Crossref"],
        ),
        Article(
            doi="10.1000/old",
            title="A long older multiple sclerosis article for filtering",
            pub_date=(today - timedelta(days=20)).isoformat(),
            discovery_sources=["Crossref"],
        ),
    ]
    repo.upsert_articles(articles)
    recent = repo.list_articles(days=5)
    assert len(recent) == 1
    assert recent[0]["doi"] == "10.1000/new"

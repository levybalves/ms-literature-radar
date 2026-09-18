from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from radar.db import Repository
from radar.models import Article


class PeriodFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.tempdir.name) / "test.sqlite3")

        today = date.today()
        self.repo.upsert_articles(
            [
                Article(
                    pmid="1",
                    title="Hoje",
                    pub_date=today.isoformat(),
                    primary_topic="immunology",
                ),
                Article(
                    pmid="2",
                    title="Quatro dias atrás",
                    pub_date=(today - timedelta(days=4)).isoformat(),
                    primary_topic="genetics",
                ),
                Article(
                    pmid="3",
                    title="Cinco dias atrás",
                    pub_date=(today - timedelta(days=5)).isoformat(),
                    primary_topic="genetics",
                ),
            ]
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_five_days_means_today_plus_previous_four_days(self) -> None:
        rows = self.repo.list_articles(days=5)
        self.assertEqual({row["pmid"] for row in rows}, {"1", "2"})

    def test_all_period_keeps_full_history(self) -> None:
        rows = self.repo.list_articles(days=None)
        self.assertEqual(len(rows), 3)

    def test_stats_follow_selected_period(self) -> None:
        stats = self.repo.stats(days=5)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["all_time_total"], 3)
        self.assertEqual(stats["by_topic"], {"immunology": 1, "genetics": 1})


if __name__ == "__main__":
    unittest.main()

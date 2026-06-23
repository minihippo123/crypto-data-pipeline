from datetime import datetime, timedelta
from decimal import Decimal

from crypto_pipeline.models import Candle
from crypto_pipeline.pipeline import DataQualityPipeline
from crypto_pipeline.repository import SQLiteRepository


def candle(minute: int) -> Candle:
    price = Decimal(100 + minute)
    return Candle(
        symbol="DEMO",
        interval="1m",
        timestamp=datetime(2026, 1, 1) + timedelta(minutes=minute),
        open=price,
        high=price + 2,
        low=price - 1,
        close=price + 1,
        volume=Decimal("1"),
    )


class StaticSource:
    def __init__(self, rows: list[Candle]) -> None:
        self.rows = rows

    def fetch_range(self, symbol, interval, start, end):
        return [row for row in self.rows if start <= row.timestamp <= end]


def repository(tmp_path) -> SQLiteRepository:
    return SQLiteRepository(f"sqlite:///{tmp_path / 'quality.db'}")


def test_full_repair_revalidates_and_recalculates(tmp_path):
    repo = repository(tmp_path)
    try:
        complete = [candle(index) for index in range(8)]
        repo.upsert_candles([row for index, row in enumerate(complete) if index not in (2, 3)])

        result = DataQualityPipeline(repo, StaticSource([complete[2], complete[3]])).run(
            "DEMO", "1m", repair=True
        )

        assert result["status"] == "SUCCESS"
        assert result["gaps_repaired"] == 1
        assert result["remaining_missing_candles"] == 0
        assert result["original_indicator_ranges"] == 1
        assert result["merged_indicator_ranges"] == 1
        assert result["indicator_ranges_completed"] == 1
        assert result["indicators_recalculated"] == 2
        assert result["unresolved_indicator_ranges"] == 0
    finally:
        repo.close()


def test_partial_repair_is_not_queued(tmp_path):
    repo = repository(tmp_path)
    try:
        complete = [candle(index) for index in range(8)]
        repo.upsert_candles([row for index, row in enumerate(complete) if index not in (2, 3)])

        result = DataQualityPipeline(repo, StaticSource([complete[2]])).run(
            "DEMO", "1m", repair=True
        )

        assert result["status"] == "PARTIAL"
        assert result["partial_gaps"] == 1
        assert result["gaps_repaired"] == 0
        assert result["indicator_ranges_queued"] == 0
        assert result["remaining_missing_candles"] == 1
    finally:
        repo.close()


def test_adjacent_queue_ranges_are_merged(tmp_path):
    repo = repository(tmp_path)
    try:
        rows = [candle(index) for index in range(10)]
        repo.upsert_candles(rows)
        repo.enqueue_indicator_range("DEMO", "1m", rows[2].timestamp, rows[3].timestamp)
        repo.enqueue_indicator_range("DEMO", "1m", rows[4].timestamp, rows[5].timestamp)

        result = DataQualityPipeline(repo).run("DEMO", "1m", repair=False)

        assert result["original_indicator_ranges"] == 2
        assert result["merged_indicator_ranges"] == 1
        assert result["indicator_ranges_completed"] == 1
        assert result["indicators_recalculated"] == 4
    finally:
        repo.close()

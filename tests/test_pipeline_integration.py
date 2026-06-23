from datetime import datetime, timedelta
from decimal import Decimal

from crypto_pipeline.models import Candle
from crypto_pipeline.pipeline import DataQualityPipeline
from crypto_pipeline.repository import SQLiteRepository


class Source:
    def __init__(self, rows):
        self.rows = rows

    def fetch_range(self, symbol, interval, start, end):
        return [row for row in self.rows if start <= row.timestamp <= end]


def test_end_to_end_gap_repair_and_revalidation(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'pipeline.sqlite3'}"
    repository = SQLiteRepository(database_url)
    start = datetime(2026, 1, 1)
    complete = []
    for index in range(10):
        price = Decimal(100 + index)
        complete.append(
            Candle(
                "DEMO",
                "1m",
                start + timedelta(minutes=index),
                price,
                price + 2,
                price - 1,
                price + 1,
                Decimal("1"),
            )
        )
    damaged = [row for index, row in enumerate(complete) if index not in (3, 4)]
    missing = [row for index, row in enumerate(complete) if index in (3, 4)]
    repository.upsert_candles(damaged)

    result = DataQualityPipeline(repository, Source(missing)).run("DEMO", "1m", repair=True)

    assert result["status"] == "SUCCESS"
    assert result["rows"] == 10
    assert result["gaps_detected"] == 1
    assert result["rows_repaired"] == 2
    assert result["remaining_gaps"] == 0
    assert result["gaps_repaired"] == 1
    assert result["indicator_ranges_queued"] == 1
    assert result["indicator_ranges_completed"] == 1
    assert result["indicators_recalculated"] == 2
    assert result["unresolved_indicator_ranges"] == 0

    audit_count = repository.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    indicator_count = repository.connection.execute("SELECT COUNT(*) FROM indicators").fetchone()[0]
    assert audit_count == 7
    assert indicator_count == 2
    repository.close()

import argparse
import json
from datetime import datetime, timedelta
from decimal import Decimal

from .config import Settings
from .models import Candle
from .pipeline import DataQualityPipeline
from .repository import SQLiteRepository
from .source import HttpCandleSource

SUPPORTED_INTERVALS = ("1m", "3m", "5m", "10m", "15m", "30m")
INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30}


class DemoSource:
    def __init__(self, rows: list[Candle]) -> None:
        self.rows = rows

    def fetch_range(self, symbol, interval, start, end):
        return [
            row
            for row in self.rows
            if row.symbol == symbol and row.interval == interval and start <= row.timestamp <= end
        ]


def build_demo_rows(interval: str) -> tuple[list[Candle], list[Candle]]:
    start = datetime(2026, 1, 1)
    complete = []
    for index in range(10):
        price = Decimal(100 + index)
        complete.append(
            Candle(
                "DEMO",
                interval,
                start + timedelta(minutes=index * INTERVAL_MINUTES[interval]),
                price,
                price + 2,
                price - 1,
                price + 1,
                Decimal("1"),
            )
        )
    damaged = [row for index, row in enumerate(complete) if index not in (3, 4)]
    missing = [row for index, row in enumerate(complete) if index in (3, 4)]
    return damaged, missing


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the public crypto data pipeline")
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--interval", choices=SUPPORTED_INTERVALS, default="1m")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env()
    repository = SQLiteRepository(settings.database_url)
    source = None
    symbol = args.symbol
    repair = args.repair

    try:
        if args.demo:
            repository.connection.execute("DELETE FROM audit_events")
            repository.connection.execute("DELETE FROM indicator_recalc_queue")
            repository.connection.execute("DELETE FROM indicators")
            repository.connection.execute("DELETE FROM candles")
            repository.connection.commit()
            damaged, missing = build_demo_rows(args.interval)
            repository.upsert_candles(damaged)
            source = DemoSource(missing)
            symbol = "DEMO"
            repair = True
        elif repair:
            source = HttpCandleSource(
                settings.source_api_base_url,
                settings.source_api_timeout_seconds,
            )

        result = DataQualityPipeline(repository, source).run(
            symbol,
            args.interval,
            repair=repair,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        repository.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from .config import DataQualityConfig
from .db import Database
from .migrations import apply_migrations
from .models import Dataset, RunStats
from .repository import DataQualityRepository


def build_dataset(symbol: str, interval: str) -> Dataset:
    lower = symbol.lower()
    return Dataset(
        id=None,
        source="bithumb",
        symbol=symbol,
        interval=interval,
        candle_table=f"bithumb_{lower}_candles",
        indicator_table=f"bithumb_{lower}_{interval}_indicators",
    )


def run(mode: str) -> dict:
    config = DataQualityConfig.from_env()
    db = Database.from_env()
    try:
        apply_migrations(db)
        repo = DataQualityRepository(db)
        started_at = datetime.now().replace(microsecond=0)
        run_id = repo.create_run(mode, started_at)
        stats = RunStats()
        for symbol in config.bithumb_symbols:
            for interval in config.bithumb_intervals:
                dataset = repo.upsert_dataset(build_dataset(symbol, interval))
                stats.datasets_checked += 1
                repo.record_check(
                    run_id,
                    dataset.id,
                    "DATASET_REGISTERED",
                    "SUCCESS",
                    started_at - timedelta(hours=config.incremental_lookback_hours),
                    started_at,
                    expected_value=1,
                    actual_value=1,
                    details={"source": dataset.source, "symbol": symbol, "interval": interval},
                )
                stats.checks_passed += 1
        repo.finish_run(run_id, datetime.now(), "SUCCESS", stats)
        return {"run_id": run_id, "status": "SUCCESS", "datasets_checked": stats.datasets_checked}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="auto", choices=("auto", "incremental", "deep", "full"))
    args = parser.parse_args()
    print(run(args.mode))


if __name__ == "__main__":
    main()

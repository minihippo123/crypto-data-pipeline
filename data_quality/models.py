from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Dataset:
    id: int | None
    source: str
    symbol: str
    interval: str
    candle_table: str
    indicator_table: str
    actual_first_timestamp: datetime | None = None
    actual_last_timestamp: datetime | None = None


@dataclass
class IndicatorQueueItem:
    id: int
    run_id: str
    dataset_id: int
    affected_start: datetime
    affected_end: datetime
    status: str
    attempts: int
    error_message: str | None = None


@dataclass
class RunStats:
    datasets_checked: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    gaps_detected: int = 0
    rows_repaired: int = 0
    indicator_ranges_queued: int = 0
    indicator_ranges_completed: int = 0
    indicator_ranges_failed: int = 0
    indicators_recalculated: int = 0
    unresolved_errors: int = 0

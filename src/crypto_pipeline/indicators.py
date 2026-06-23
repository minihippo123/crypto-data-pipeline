from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .repository import SQLiteRepository


@dataclass(frozen=True, slots=True)
class IndicatorRepairResult:
    calculated_rows: int
    inserted_rows: int
    updated_rows: int
    warmup_rows: int


def recalculate_sma3_range(
    repository: SQLiteRepository,
    symbol: str,
    interval: str,
    affected_start: datetime,
    affected_end: datetime,
) -> IndicatorRepairResult:
    warmup = repository.list_candles_before(symbol, interval, affected_start, limit=2)
    affected = repository.list_candles_range(symbol, interval, affected_start, affected_end)
    rows = warmup + affected

    inserted = 0
    updated = 0
    closes: list[Decimal] = []

    for candle in rows:
        closes.append(candle.close)
        if candle.timestamp < affected_start:
            continue
        value = sum(closes[-3:]) / Decimal(3) if len(closes) >= 3 else None
        outcome = repository.upsert_sma3(candle, value)
        if outcome == "inserted":
            inserted += 1
        else:
            updated += 1

    return IndicatorRepairResult(
        calculated_rows=len(affected),
        inserted_rows=inserted,
        updated_rows=updated,
        warmup_rows=len(warmup),
    )

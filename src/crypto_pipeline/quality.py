from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Iterable

from .models import Candle, Gap

INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30}


def detect_duplicates(candles: Iterable[Candle]) -> list[Candle]:
    rows = list(candles)
    counts = Counter((r.symbol, r.interval, r.timestamp) for r in rows)
    return [r for r in rows if counts[(r.symbol, r.interval, r.timestamp)] > 1]


def detect_invalid(candles: Iterable[Candle]) -> list[tuple[Candle, list[str]]]:
    return [(c, errors) for c in candles if (errors := c.validate())]


def detect_gaps(candles: Iterable[Candle]) -> list[Gap]:
    rows = sorted(candles, key=lambda r: r.timestamp)
    if len(rows) < 2:
        return []
    step = timedelta(minutes=_interval_minutes(rows[0].interval))
    gaps: list[Gap] = []
    previous = rows[0]
    for current in rows[1:]:
        if current.symbol != previous.symbol or current.interval != previous.interval:
            raise ValueError("detect_gaps accepts one symbol/interval dataset at a time")
        missing = int((current.timestamp - previous.timestamp) / step) - 1
        if missing > 0:
            gaps.append(Gap(current.symbol, current.interval, previous.timestamp + step, current.timestamp - step, missing))
        previous = current
    return gaps


def _interval_minutes(interval: str) -> int:
    if interval not in INTERVAL_MINUTES:
        raise ValueError(f"unsupported interval: {interval}")
    return INTERVAL_MINUTES[interval]

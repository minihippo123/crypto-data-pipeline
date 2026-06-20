from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Iterable

from .models import Candle, Gap


INTERVAL_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}


def detect_duplicates(candles: Iterable[Candle]) -> list[Candle]:
    rows = list(candles)
    counts = Counter((row.symbol, row.interval, row.timestamp) for row in rows)
    return [row for row in rows if counts[(row.symbol, row.interval, row.timestamp)] > 1]


def detect_invalid(candles: Iterable[Candle]) -> list[tuple[Candle, list[str]]]:
    findings: list[tuple[Candle, list[str]]] = []
    for candle in candles:
        errors = candle.validate()
        if errors:
            findings.append((candle, errors))
    return findings


def detect_gaps(candles: Iterable[Candle]) -> list[Gap]:
    rows = sorted(candles, key=lambda row: row.timestamp)
    if len(rows) < 2:
        return []
    interval = rows[0].interval
    step = timedelta(minutes=_interval_minutes(interval))
    gaps: list[Gap] = []
    previous = rows[0]
    for current in rows[1:]:
        if current.symbol != previous.symbol or current.interval != previous.interval:
            raise ValueError("detect_gaps accepts one symbol/interval dataset at a time")
        missing = int((current.timestamp - previous.timestamp) / step) - 1
        if missing > 0:
            gaps.append(
                Gap(
                    symbol=current.symbol,
                    interval=current.interval,
                    start=previous.timestamp + step,
                    end=current.timestamp - step,
                    expected_count=missing,
                )
            )
        previous = current
    return gaps


def _interval_minutes(interval: str) -> int:
    try:
        return INTERVAL_MINUTES[interval]
    except KeyError as exc:
        raise ValueError(f"unsupported interval: {interval}") from exc

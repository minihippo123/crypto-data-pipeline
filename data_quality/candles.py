from __future__ import annotations

from datetime import datetime, timedelta

INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30}


def expected_timestamps(start: datetime, end: datetime, interval: str) -> list[datetime]:
    step = timedelta(minutes=INTERVAL_MINUTES[interval])
    output = []
    cursor = start
    while cursor <= end:
        output.append(cursor)
        cursor += step
    return output


def find_gap_ranges(timestamps: list[datetime], interval: str) -> list[tuple[datetime, datetime]]:
    if len(timestamps) < 2:
        return []
    step = timedelta(minutes=INTERVAL_MINUTES[interval])
    ranges = []
    ordered = sorted(set(timestamps))
    for previous, current in zip(ordered, ordered[1:]):
        if current - previous > step:
            ranges.append((previous + step, current - step))
    return ranges

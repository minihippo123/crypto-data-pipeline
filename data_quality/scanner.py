from __future__ import annotations

from .candles import find_gap_ranges


class DataQualityScanner:
    def __init__(self, db):
        self.db = db

    def candle_timestamps(self, table: str, interval: str, start, end):
        rows = self.db.fetchall(
            f"SELECT timestamp FROM {table} WHERE `interval`=%s AND timestamp BETWEEN %s AND %s ORDER BY timestamp",
            (interval, start, end),
        )
        return [row["timestamp"] for row in rows]

    def gap_ranges(self, table: str, interval: str, start, end):
        return find_gap_ranges(self.candle_timestamps(table, interval, start, end), interval)

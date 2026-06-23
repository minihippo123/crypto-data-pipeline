from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .models import AuditEvent, Candle


SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    volume TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, timestamp)
);

CREATE TABLE IF NOT EXISTS indicators (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    sma_3 TEXT,
    PRIMARY KEY (symbol, interval, timestamp)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indicator_recalc_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    affected_start TEXT NOT NULL,
    affected_end TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_indicator_queue_status
ON indicator_recalc_queue(status, symbol, interval, affected_start);
"""


class SQLiteRepository:
    def __init__(self, database_url: str) -> None:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("public demo currently supports sqlite:/// URLs")
        path = Path(database_url.removeprefix(prefix))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def upsert_candles(self, candles: list[Candle]) -> int:
        written = 0
        with self.connection:
            for candle in candles:
                self.connection.execute(
                    """
                    INSERT INTO candles (
                        symbol, interval, timestamp, open, high, low, close, volume
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, interval, timestamp) DO UPDATE SET
                        open=excluded.open,
                        high=excluded.high,
                        low=excluded.low,
                        close=excluded.close,
                        volume=excluded.volume
                    """,
                    (
                        candle.symbol,
                        candle.interval,
                        candle.timestamp.isoformat(),
                        str(candle.open),
                        str(candle.high),
                        str(candle.low),
                        str(candle.close),
                        str(candle.volume),
                    ),
                )
                written += 1
        return written

    def list_candles(self, symbol: str, interval: str) -> list[Candle]:
        rows = self.connection.execute(
            """
            SELECT symbol, interval, timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND interval = ?
            ORDER BY timestamp
            """,
            (symbol, interval),
        ).fetchall()
        return [self._row_to_candle(row) for row in rows]

    def list_candles_range(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[Candle]:
        rows = self.connection.execute(
            """
            SELECT symbol, interval, timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND interval = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
            """,
            (symbol, interval, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [self._row_to_candle(row) for row in rows]

    def list_candles_before(
        self, symbol: str, interval: str, timestamp: datetime, limit: int
    ) -> list[Candle]:
        rows = self.connection.execute(
            """
            SELECT symbol, interval, timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND interval = ? AND timestamp < ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol, interval, timestamp.isoformat(), int(limit)),
        ).fetchall()
        return [self._row_to_candle(row) for row in reversed(rows)]

    def upsert_sma3(self, candle: Candle, value: Decimal | None) -> str:
        exists = self.connection.execute(
            """
            SELECT 1 FROM indicators
            WHERE symbol = ? AND interval = ? AND timestamp = ?
            """,
            (candle.symbol, candle.interval, candle.timestamp.isoformat()),
        ).fetchone()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO indicators (symbol, interval, timestamp, sma_3)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol, interval, timestamp) DO UPDATE SET sma_3=excluded.sma_3
                """,
                (
                    candle.symbol,
                    candle.interval,
                    candle.timestamp.isoformat(),
                    None if value is None else str(value),
                ),
            )
        return "updated" if exists else "inserted"

    def enqueue_indicator_range(
        self, symbol: str, interval: str, affected_start: datetime, affected_end: datetime
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO indicator_recalc_queue (
                    symbol, interval, affected_start, affected_end,
                    status, attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'PENDING', 0, ?, ?)
                """,
                (
                    symbol,
                    interval,
                    affected_start.isoformat(),
                    affected_end.isoformat(),
                    now,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    def list_queue(self, symbol: str, interval: str, status: str = "PENDING") -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT * FROM indicator_recalc_queue
            WHERE symbol = ? AND interval = ? AND status = ?
            ORDER BY affected_start, affected_end, id
            """,
            (symbol, interval, status),
        ).fetchall()

    def supersede_queue_items(self, ids: list[int]) -> None:
        if not ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in ids)
        with self.connection:
            self.connection.execute(
                f"""
                UPDATE indicator_recalc_queue
                SET status = 'SUPERSEDED', updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (now, *ids),
            )

    def mark_queue_running(self, queue_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute(
                """
                UPDATE indicator_recalc_queue
                SET status='RUNNING', attempts=attempts+1, error_message=NULL, updated_at=?
                WHERE id=?
                """,
                (now, queue_id),
            )

    def mark_queue_completed(self, queue_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute(
                """
                UPDATE indicator_recalc_queue
                SET status='SUCCESS', updated_at=? WHERE id=?
                """,
                (now, queue_id),
            )

    def mark_queue_failed(self, queue_id: int, error_message: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute(
                """
                UPDATE indicator_recalc_queue
                SET status='FAILED', error_message=?, updated_at=? WHERE id=?
                """,
                (error_message[:1000], now, queue_id),
            )

    def count_queue(self, symbol: str, interval: str, status: str) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM indicator_recalc_queue
            WHERE symbol=? AND interval=? AND status=?
            """,
            (symbol, interval, status),
        ).fetchone()
        return int(row["count"])

    def write_audit_event(self, event: AuditEvent) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO audit_events (run_id, stage, status, occurred_at, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.stage,
                    event.status,
                    event.occurred_at.isoformat(),
                    json.dumps(event.details, sort_keys=True, default=str),
                ),
            )

    @staticmethod
    def _row_to_candle(row: sqlite3.Row) -> Candle:
        return Candle(
            symbol=row["symbol"],
            interval=row["interval"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal(row["volume"]),
        )

    def close(self) -> None:
        self.connection.close()

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
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
        inserted = 0
        for candle in candles:
            cursor = self.connection.execute(
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
            inserted += cursor.rowcount
            self.connection.commit()
        return inserted

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
        return [
            Candle(
                symbol=row["symbol"],
                interval=row["interval"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=Decimal(row["volume"]),
            )
            for row in rows
        ]

    def upsert_sma3(self, candle: Candle, value: Decimal | None) -> None:
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
        self.connection.commit()

    def write_audit_event(self, event: AuditEvent) -> None:
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
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

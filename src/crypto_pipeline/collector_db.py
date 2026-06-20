from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_candles (
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (exchange, symbol, interval, timestamp)
);
CREATE TABLE IF NOT EXISTS market_trades (
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    price REAL NOT NULL,
    volume REAL NOT NULL,
    side TEXT,
    PRIMARY KEY (exchange, symbol, trade_id)
);
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    best_bid REAL NOT NULL,
    best_ask REAL NOT NULL,
    bid_volume REAL NOT NULL,
    ask_volume REAL NOT NULL,
    spread REAL NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (exchange, symbol, timestamp)
);
CREATE TABLE IF NOT EXISTS account_snapshots (
    exchange TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    total_value REAL NOT NULL,
    balances_json TEXT NOT NULL,
    PRIMARY KEY (exchange, timestamp)
);
"""


class CollectorDatabase:
    def __init__(self, database_url: str) -> None:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("collector demo supports sqlite:/// URLs")
        path = Path(database_url.removeprefix(prefix))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def save_candles(self, exchange: str, symbol: str, interval: str, rows: list[dict]) -> int:
        count = 0
        for row in rows:
            self.connection.execute(
                """
                INSERT INTO market_candles
                (exchange, symbol, interval, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol, interval, timestamp) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume
                """,
                (exchange, symbol, interval, row["timestamp"].isoformat(), row["open"], row["high"], row["low"], row["close"], row["volume"]),
            )
            count += 1
        self.connection.commit()
        return count

    def save_trades(self, exchange: str, symbol: str, rows: list[dict]) -> int:
        count = 0
        for row in rows:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO market_trades
                (exchange, symbol, trade_id, timestamp, price, volume, side)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (exchange, symbol, str(row["trade_id"]), row["timestamp"].isoformat(), row["price"], row["volume"], row.get("side")),
            )
            count += 1
        self.connection.commit()
        return count

    def save_orderbook(self, exchange: str, symbol: str, row: dict) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO orderbook_snapshots
            (exchange, symbol, timestamp, best_bid, best_ask, bid_volume, ask_volume, spread, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (exchange, symbol, row["timestamp"].isoformat(), row["best_bid"], row["best_ask"], row["bid_volume"], row["ask_volume"], row["spread"], json.dumps(row["payload"])),
        )
        self.connection.commit()

    def save_account_snapshot(self, exchange: str, total_value: float, balances: list[dict]) -> None:
        timestamp = datetime.utcnow().replace(microsecond=0).isoformat()
        self.connection.execute(
            "INSERT OR REPLACE INTO account_snapshots (exchange, timestamp, total_value, balances_json) VALUES (?, ?, ?, ?)",
            (exchange, timestamp, total_value, json.dumps(balances, sort_keys=True)),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path


def _name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]", "_", value.lower())
    if not cleaned or cleaned[0].isdigit():
        raise ValueError(f"invalid identifier: {value}")
    return cleaned


class CollectorDatabase:
    def __init__(self, database_url: str) -> None:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("public collector build supports sqlite:/// URLs")
        path = Path(database_url.removeprefix(prefix))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.commit()
        self._ensure_global_tables()

    def _ensure_global_tables(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS symbol_orderbook_status (
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                current_price REAL NOT NULL,
                bid_price REAL NOT NULL,
                ask_price REAL NOT NULL,
                spread REAL NOT NULL,
                bid_volume REAL NOT NULL,
                ask_volume REAL NOT NULL,
                bid_total_volume REAL NOT NULL,
                ask_total_volume REAL NOT NULL,
                book_imbalance REAL NOT NULL,
                bid_imbalance REAL NOT NULL,
                ask_imbalance REAL NOT NULL,
                imbalance_ratio REAL NOT NULL,
                orderbook_pressure REAL NOT NULL,
                spread_pct REAL NOT NULL,
                vwap_5 REAL NOT NULL,
                liquidity_density REAL NOT NULL,
                PRIMARY KEY (exchange, symbol)
            );
            CREATE TABLE IF NOT EXISTS account_snapshots (
                exchange TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                total_value REAL NOT NULL,
                balances_json TEXT NOT NULL,
                PRIMARY KEY (exchange, timestamp)
            );
            CREATE TABLE IF NOT EXISTS collector_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collector TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def ping(self) -> None:
        self.connection.execute("SELECT 1").fetchone()

    def ensure_market_tables(self, exchange: str, symbol: str) -> None:
        prefix = f"{_name(exchange)}_{_name(symbol)}"
        self.connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {prefix}_candles (
                timestamp TEXT NOT NULL,
                candle_interval TEXT NOT NULL,
                open_price REAL NOT NULL,
                high_price REAL NOT NULL,
                low_price REAL NOT NULL,
                close_price REAL NOT NULL,
                volume REAL NOT NULL,
                trade_amount REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (timestamp, candle_interval)
            );
            CREATE TABLE IF NOT EXISTS {prefix}_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                price REAL NOT NULL,
                volume REAL NOT NULL,
                total_value REAL NOT NULL,
                is_buyer_maker INTEGER NOT NULL,
                vwap REAL NOT NULL,
                UNIQUE(timestamp, price, volume, total_value, is_buyer_maker)
            );
            CREATE TABLE IF NOT EXISTS {prefix}_orderbooks (
                timestamp TEXT PRIMARY KEY,
                bid_price REAL NOT NULL,
                bid_volume REAL NOT NULL,
                ask_price REAL NOT NULL,
                ask_volume REAL NOT NULL,
                bid_total_volume REAL NOT NULL,
                ask_total_volume REAL NOT NULL,
                spread REAL NOT NULL,
                book_imbalance REAL NOT NULL,
                bid_imbalance REAL NOT NULL,
                ask_imbalance REAL NOT NULL,
                imbalance_ratio REAL NOT NULL,
                orderbook_pressure REAL NOT NULL,
                spread_pct REAL NOT NULL,
                vwap_5 REAL NOT NULL,
                liquidity_density REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS {prefix}_orderbook_levels (
                level INTEGER PRIMARY KEY,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                total REAL NOT NULL,
                current_price REAL NOT NULL,
                timestamp TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def ensure_indicator_table(self, exchange: str, symbol: str, interval: str) -> str:
        table = f"{_name(exchange)}_{_name(symbol)}_{_name(interval)}_indicators"
        self.connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                timestamp TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL
            )
            """
        )
        self.connection.commit()
        return table

    def save_candles(self, exchange: str, symbol: str, interval: str, rows: list[dict]) -> int:
        self.ensure_market_tables(exchange, symbol)
        table = f"{_name(exchange)}_{_name(symbol)}_candles"
        written = 0
        for row in rows:
            trade_amount = float(row.get("trade_amount", row["close"] * row["volume"]))
            self.connection.execute(
                f"""
                INSERT INTO {table}
                (timestamp, candle_interval, open_price, high_price, low_price, close_price, volume, trade_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(timestamp, candle_interval) DO UPDATE SET
                    open_price=excluded.open_price,
                    high_price=excluded.high_price,
                    low_price=excluded.low_price,
                    close_price=excluded.close_price,
                    volume=excluded.volume,
                    trade_amount=excluded.trade_amount
                """,
                (row["timestamp"].isoformat(), interval, row["open"], row["high"], row["low"], row["close"], row["volume"], trade_amount),
            )
            written += 1
        self.connection.commit()
        return written

    def get_candles(self, exchange: str, symbol: str, interval: str, limit: int = 200) -> list[dict]:
        self.ensure_market_tables(exchange, symbol)
        table = f"{_name(exchange)}_{_name(symbol)}_candles"
        rows = self.connection.execute(
            f"""
            SELECT timestamp, open_price, high_price, low_price, close_price, volume
            FROM {table}
            WHERE candle_interval = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (interval, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def save_trades(self, exchange: str, symbol: str, rows: list[dict]) -> int:
        self.ensure_market_tables(exchange, symbol)
        table = f"{_name(exchange)}_{_name(symbol)}_trades"
        written = 0
        for row in rows:
            cursor = self.connection.execute(
                f"""
                INSERT OR IGNORE INTO {table}
                (timestamp, price, volume, total_value, is_buyer_maker, vwap)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (row["timestamp"].isoformat(), round(float(row["price"]), 8), round(float(row["volume"]), 8), round(float(row.get("total_value", row["price"] * row["volume"])), 8), int(row.get("is_buyer_maker", 0)), round(float(row.get("vwap", 0)), 8)),
            )
            written += cursor.rowcount
        self.connection.commit()
        return written

    def save_orderbook(self, exchange: str, symbol: str, row: dict) -> None:
        self.ensure_market_tables(exchange, symbol)
        table = f"{_name(exchange)}_{_name(symbol)}_orderbooks"
        self.connection.execute(
            f"""
            INSERT OR REPLACE INTO {table}
            (timestamp, bid_price, bid_volume, ask_price, ask_volume, bid_total_volume, ask_total_volume, spread, book_imbalance, bid_imbalance, ask_imbalance, imbalance_ratio, orderbook_pressure, spread_pct, vwap_5, liquidity_density)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row["timestamp"].isoformat(), row["bid_price"], row["bid_volume"], row["ask_price"], row["ask_volume"], row["bid_total_volume"], row["ask_total_volume"], row["spread"], row["book_imbalance"], row["bid_imbalance"], row["ask_imbalance"], row.get("imbalance_ratio", 0), row.get("orderbook_pressure", 0), row.get("spread_pct", 0), row.get("vwap_5", 0), row.get("liquidity_density", 0)),
        )
        self.connection.commit()

    def save_orderbook_depth(self, exchange: str, symbol: str, row: dict, levels: int = 30) -> None:
        self.ensure_market_tables(exchange, symbol)
        table = f"{_name(exchange)}_{_name(symbol)}_orderbook_levels"
        bids = list(row.get("bids_levels") or [])[:levels]
        asks = list(row.get("asks_levels") or [])[:levels]
        bids += [[0.0, 0.0]] * (levels - len(bids))
        asks += [[0.0, 0.0]] * (levels - len(asks))
        current_price = (float(row["bid_price"]) + float(row["ask_price"])) / 2
        values = []
        for index, (price, quantity) in enumerate(bids):
            level = -(levels - index)
            values.append((level, "bid", price, quantity, price * quantity, current_price, row["timestamp"].isoformat()))
        values.append((0, "mid", current_price, 0.0, 0.0, current_price, row["timestamp"].isoformat()))
        for index, (price, quantity) in enumerate(asks):
            values.append((index + 1, "ask", price, quantity, price * quantity, current_price, row["timestamp"].isoformat()))
        self.connection.executemany(
            f"""
            INSERT OR REPLACE INTO {table}
            (level, side, price, quantity, total, current_price, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        self.connection.commit()

    def save_orderbook_status(self, exchange: str, symbol: str, row: dict) -> None:
        current_price = (float(row["bid_price"]) + float(row["ask_price"])) / 2
        self.connection.execute(
            """
            INSERT OR REPLACE INTO symbol_orderbook_status
            (exchange, symbol, timestamp, current_price, bid_price, ask_price, spread, bid_volume, ask_volume, bid_total_volume, ask_total_volume, book_imbalance, bid_imbalance, ask_imbalance, imbalance_ratio, orderbook_pressure, spread_pct, vwap_5, liquidity_density)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (exchange, symbol, row["timestamp"].isoformat(), current_price, row["bid_price"], row["ask_price"], row["spread"], row["bid_volume"], row["ask_volume"], row["bid_total_volume"], row["ask_total_volume"], row["book_imbalance"], row["bid_imbalance"], row["ask_imbalance"], row.get("imbalance_ratio", 0), row.get("orderbook_pressure", 0), row.get("spread_pct", 0), row.get("vwap_5", 0), row.get("liquidity_density", 0)),
        )
        self.connection.commit()

    def save_indicators(self, exchange: str, symbol: str, interval: str, timestamp: datetime, indicators: dict) -> None:
        table = self.ensure_indicator_table(exchange, symbol, interval)
        self.connection.execute(
            f"INSERT OR REPLACE INTO {table} (timestamp, payload_json) VALUES (?, ?)",
            (timestamp.isoformat(), json.dumps(indicators, sort_keys=True, default=str)),
        )
        self.connection.commit()

    def save_account_snapshot(self, exchange: str, total_value: float, balances: list[dict]) -> None:
        timestamp = datetime.utcnow().replace(microsecond=0).isoformat()
        self.connection.execute(
            "INSERT OR REPLACE INTO account_snapshots (exchange, timestamp, total_value, balances_json) VALUES (?, ?, ?, ?)",
            (exchange, timestamp, total_value, json.dumps(balances, sort_keys=True)),
        )
        self.connection.commit()

    def log_event(self, collector: str, event_type: str, status: str, details: dict) -> None:
        self.connection.execute(
            "INSERT INTO collector_events (collector, event_type, status, occurred_at, details_json) VALUES (?, ?, ?, ?, ?)",
            (collector, event_type, status, datetime.utcnow().isoformat(), json.dumps(details, sort_keys=True, default=str)),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

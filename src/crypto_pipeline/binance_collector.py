from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime

import requests

from .collector_db import CollectorDatabase
from .technical_indicators import calculate_indicators, calculate_orderbook_indicators

SUPPORTED_INTERVALS = ("1m", "3m", "5m", "10m", "15m", "30m")
BINANCE_NATIVE_INTERVALS = {"1m", "3m", "5m", "15m", "30m"}
LOGGER = logging.getLogger(__name__)


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in os.getenv(name, default).split(",") if item.strip())


class BinanceCollector:
    def __init__(self, database: CollectorDatabase) -> None:
        self.database = database
        self.base_url = os.getenv("BINANCE_BASE_URL", "https://api.binance.com/api/v3").rstrip("/")
        self.symbols = _csv("BINANCE_SYMBOLS", "BTCUSDT,ETHUSDT,XRPUSDT,SOLUSDT,SUIUSDT")
        self.intervals = SUPPORTED_INTERVALS
        self.timeout = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
        self.max_retries = int(os.getenv("HTTP_MAX_RETRIES", "3"))
        self.retry_delay = float(os.getenv("HTTP_RETRY_DELAY_SECONDS", "1"))
        self.update_interval = float(os.getenv("BINANCE_UPDATE_INTERVAL_SECONDS", "0.1"))
        self.api_call_sleep = float(os.getenv("BINANCE_API_CALL_SLEEP_SECONDS", "0.1"))
        self.symbol_sleep = float(os.getenv("BINANCE_SYMBOL_SLEEP_SECONDS", "0.5"))
        self.trades_limit = int(os.getenv("BINANCE_TRADES_LIMIT", "1000"))
        self.klines_limit = int(os.getenv("BINANCE_KLINES_LIMIT", "1000"))
        self.orderbook_limit = int(os.getenv("BINANCE_ORDERBOOK_LIMIT", "100"))
        self.session = requests.Session()
        self.last_heartbeat = 0.0
        self.last_timestamps = {
            symbol: {
                "trades": None,
                "orderbook": None,
                "candles": {interval: None for interval in self.intervals},
            }
            for symbol in self.symbols
        }
        for symbol in self.symbols:
            self.database.ensure_market_tables("binance", self._base_symbol(symbol))

    @staticmethod
    def _base_symbol(symbol: str) -> str:
        return symbol[:-4] if symbol.endswith("USDT") else symbol

    def _heartbeat(self) -> None:
        now = time.time()
        if now - self.last_heartbeat >= 300:
            self.database.ping()
            self.database.log_event(
                "binance_collector", "heartbeat", "SUCCESS", {"symbols": list(self.symbols)}
            )
            LOGGER.info("BinanceCollector running")
            self.last_heartbeat = now

    def _get(self, endpoint: str, params: dict) -> object:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(
                    f"{self.base_url}{endpoint}", params=params, timeout=self.timeout
                )
                if response.status_code == 429:
                    delay = float(response.headers.get("Retry-After", self.retry_delay * attempt))
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)
        raise RuntimeError(f"Binance request failed: {last_error}")

    def _is_duplicate(self, symbol: str, data_type: str, timestamp: datetime, interval: str | None = None) -> bool:
        previous = self.last_timestamps[symbol][data_type]
        if interval:
            previous = previous[interval]
        if previous and timestamp <= previous:
            return True
        if interval:
            self.last_timestamps[symbol][data_type][interval] = timestamp
        else:
            self.last_timestamps[symbol][data_type] = timestamp
        return False

    def _fetch_native_candles(self, symbol: str, interval: str, limit: int | None = None) -> list[dict]:
        if interval not in BINANCE_NATIVE_INTERVALS:
            raise ValueError(f"unsupported Binance source interval: {interval}")
        payload = self._get(
            "/klines",
            {"symbol": symbol, "interval": interval, "limit": limit or self.klines_limit},
        )
        if not isinstance(payload, list):
            raise RuntimeError("unexpected Binance kline response")
        rows = []
        for item in payload:
            timestamp = datetime.fromtimestamp(item[0] / 1000)
            if self._is_duplicate(symbol, "candles", timestamp, interval):
                continue
            rows.append(
                {
                    "timestamp": timestamp,
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                    "trade_amount": float(item[7]) if len(item) > 7 else float(item[4]) * float(item[5]),
                }
            )
        return rows

    @staticmethod
    def _aggregate_10m(rows_5m: list[dict]) -> list[dict]:
        buckets: dict[datetime, list[dict]] = {}
        for row in rows_5m:
            timestamp = row["timestamp"].replace(
                minute=(row["timestamp"].minute // 10) * 10,
                second=0,
                microsecond=0,
            )
            buckets.setdefault(timestamp, []).append(row)
        output = []
        for timestamp, bucket in sorted(buckets.items()):
            bucket.sort(key=lambda item: item["timestamp"])
            if len(bucket) != 2:
                continue
            output.append(
                {
                    "timestamp": timestamp,
                    "open": bucket[0]["open"],
                    "high": max(item["high"] for item in bucket),
                    "low": min(item["low"] for item in bucket),
                    "close": bucket[-1]["close"],
                    "volume": sum(item["volume"] for item in bucket),
                    "trade_amount": sum(item.get("trade_amount", 0) for item in bucket),
                }
            )
        return output

    def fetch_trades(self, symbol: str) -> list[dict]:
        payload = self._get("/trades", {"symbol": symbol, "limit": self.trades_limit})
        if not isinstance(payload, list):
            return []
        rows = []
        total_value = 0.0
        total_volume = 0.0
        for item in payload:
            timestamp = datetime.fromtimestamp(item["time"] / 1000)
            if self._is_duplicate(symbol, "trades", timestamp):
                continue
            price = float(item["price"])
            volume = float(item["qty"])
            total_value += price * volume
            total_volume += volume
            rows.append(
                {
                    "timestamp": timestamp,
                    "price": price,
                    "volume": volume,
                    "total_value": price * volume,
                    "is_buyer_maker": 1 if item.get("isBuyerMaker") else 0,
                }
            )
        vwap = total_value / total_volume if total_volume else 0.0
        for row in rows:
            row["vwap"] = vwap
        return rows

    def fetch_orderbook(self, symbol: str) -> dict | None:
        payload = self._get("/depth", {"symbol": symbol, "limit": self.orderbook_limit})
        if not isinstance(payload, dict) or not payload.get("bids") or not payload.get("asks"):
            return None
        timestamp = datetime.utcnow()
        bids = [[float(item[0]), float(item[1])] for item in payload["bids"][:30]]
        asks = [[float(item[0]), float(item[1])] for item in payload["asks"][:30]]
        bid_total = sum(item[1] for item in bids)
        ask_total = sum(item[1] for item in asks)
        total = bid_total + ask_total
        row = {
            "timestamp": timestamp,
            "bid_price": bids[0][0],
            "bid_volume": bids[0][1],
            "ask_price": asks[0][0],
            "ask_volume": asks[0][1],
            "bid_total_volume": bid_total,
            "ask_total_volume": ask_total,
            "spread": asks[0][0] - bids[0][0],
            "book_imbalance": bid_total / ask_total if ask_total else 0.0,
            "bid_imbalance": bid_total / total if total else 0.0,
            "ask_imbalance": ask_total / total if total else 0.0,
            "bids_levels": bids,
            "asks_levels": asks,
        }
        row.update(calculate_orderbook_indicators(row))
        return row

    def calculate_and_save_indicators(self, symbol: str, interval: str) -> bool:
        base_symbol = self._base_symbol(symbol)
        rows = self.database.get_candles("binance", base_symbol, interval, limit=200)
        result = calculate_indicators(rows)
        if result is None:
            return False
        timestamp, indicators = result
        self.database.save_indicators("binance", base_symbol, interval, timestamp, indicators)
        return True

    def collect_symbol(self, symbol: str, intervals: tuple[str, ...]) -> dict[str, int]:
        base_symbol = self._base_symbol(symbol)
        summary = {"candles_saved": 0, "trades_saved": 0, "orderbooks_saved": 0, "indicators_saved": 0}
        cache: dict[str, list[dict]] = {}
        for interval in intervals:
            if interval not in SUPPORTED_INTERVALS:
                raise ValueError(f"unsupported interval: {interval}")
            if interval == "10m":
                source_rows = cache.get("5m") or self._fetch_native_candles(symbol, "5m", 400)
                cache["5m"] = source_rows
                rows = self._aggregate_10m(source_rows)
            else:
                rows = cache.get(interval) or self._fetch_native_candles(symbol, interval)
                cache[interval] = rows
            if rows:
                summary["candles_saved"] += self.database.save_candles("binance", base_symbol, interval, rows)
                if self.calculate_and_save_indicators(symbol, interval):
                    summary["indicators_saved"] += 1
            time.sleep(self.api_call_sleep)

        trades = self.fetch_trades(symbol)
        if trades:
            summary["trades_saved"] += self.database.save_trades("binance", base_symbol, trades)
        orderbook = self.fetch_orderbook(symbol)
        if orderbook:
            self.database.save_orderbook("binance", base_symbol, orderbook)
            self.database.save_orderbook_depth("binance", base_symbol, orderbook, 30)
            self.database.save_orderbook_status("binance", base_symbol, orderbook)
            summary["orderbooks_saved"] = 1
        return summary

    def collect_once(self, intervals: tuple[str, ...] = SUPPORTED_INTERVALS) -> dict[str, int]:
        total = {"candles_saved": 0, "trades_saved": 0, "orderbooks_saved": 0, "indicators_saved": 0}
        for symbol in self.symbols:
            try:
                summary = self.collect_symbol(symbol, intervals)
                for key, value in summary.items():
                    total[key] += value
            except Exception as exc:
                LOGGER.exception("symbol collection failed %s: %s", symbol, exc)
                self.database.log_event("binance_collector", "symbol", "ERROR", {"symbol": symbol, "error": str(exc)})
            time.sleep(self.symbol_sleep)
        self.database.log_event("binance_collector", "collect_once", "SUCCESS", total)
        return total

    def run(self) -> None:
        while True:
            try:
                self._heartbeat()
                self.collect_once()
                time.sleep(self.update_interval)
            except Exception as exc:
                LOGGER.exception("collector loop failed: %s", exc)
                self.database.log_event("binance_collector", "run_loop", "ERROR", {"error": str(exc)})
                time.sleep(self.retry_delay)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    database = CollectorDatabase(os.getenv("DATABASE_URL", "sqlite:///data/crypto_pipeline.db"))
    collector = BinanceCollector(database)
    try:
        print(collector.collect_once()) if args.once else collector.run()
    finally:
        database.close()


if __name__ == "__main__":
    main()

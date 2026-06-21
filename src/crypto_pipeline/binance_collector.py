from __future__ import annotations

import argparse
import os
import time
from datetime import datetime

import requests

from .collector_db import CollectorDatabase

SUPPORTED_INTERVALS = ("1m", "3m", "5m", "10m", "15m", "30m")
BINANCE_NATIVE_INTERVALS = {"1m", "3m", "5m", "15m", "30m"}


class BinanceCollector:
    def __init__(self, database: CollectorDatabase) -> None:
        self.database = database
        self.base_url = os.getenv("BINANCE_BASE_URL", "https://api.binance.com/api/v3").rstrip("/")
        self.timeout = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
        self.max_retries = int(os.getenv("HTTP_MAX_RETRIES", "3"))
        self.retry_delay = float(os.getenv("HTTP_RETRY_DELAY_SECONDS", "1"))
        self.session = requests.Session()

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

    def _fetch_native_candles(self, symbol: str, interval: str, limit: int = 200) -> list[dict]:
        if interval not in BINANCE_NATIVE_INTERVALS:
            raise ValueError(f"unsupported Binance source interval: {interval}")
        payload = self._get("/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        if not isinstance(payload, list):
            raise RuntimeError("unexpected Binance kline response")
        return [
            {
                "timestamp": datetime.fromtimestamp(item[0] / 1000),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
            }
            for item in payload
        ]

    @staticmethod
    def _aggregate_10m(rows_5m: list[dict]) -> list[dict]:
        buckets: dict[datetime, list[dict]] = {}
        for row in rows_5m:
            ts = row["timestamp"].replace(
                minute=(row["timestamp"].minute // 10) * 10,
                second=0,
                microsecond=0,
            )
            buckets.setdefault(ts, []).append(row)

        aggregated: list[dict] = []
        for timestamp, bucket in sorted(buckets.items()):
            bucket.sort(key=lambda item: item["timestamp"])
            if len(bucket) != 2:
                continue
            aggregated.append(
                {
                    "timestamp": timestamp,
                    "open": bucket[0]["open"],
                    "high": max(item["high"] for item in bucket),
                    "low": min(item["low"] for item in bucket),
                    "close": bucket[-1]["close"],
                    "volume": sum(item["volume"] for item in bucket),
                }
            )
        return aggregated

    def collect_once(self, symbol: str, intervals: tuple[str, ...]) -> dict[str, int]:
        candles_saved = 0
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
            candles_saved += self.database.save_candles("binance", symbol, interval, rows)

        trade_payload = self._get("/trades", {"symbol": symbol, "limit": 200})
        if not isinstance(trade_payload, list):
            raise RuntimeError("unexpected Binance trades response")
        trades = [
            {
                "trade_id": item["id"],
                "timestamp": datetime.fromtimestamp(item["time"] / 1000),
                "price": float(item["price"]),
                "volume": float(item["qty"]),
                "side": "sell" if item.get("isBuyerMaker") else "buy",
            }
            for item in trade_payload
        ]
        trades_saved = self.database.save_trades("binance", symbol, trades)

        payload = self._get("/depth", {"symbol": symbol, "limit": 20})
        if not isinstance(payload, dict) or not payload.get("bids") or not payload.get("asks"):
            raise RuntimeError("unexpected Binance orderbook response")
        best_bid = payload["bids"][0]
        best_ask = payload["asks"][0]
        self.database.save_orderbook(
            "binance",
            symbol,
            {
                "timestamp": datetime.utcnow(),
                "best_bid": float(best_bid[0]),
                "best_ask": float(best_ask[0]),
                "bid_volume": float(best_bid[1]),
                "ask_volume": float(best_ask[1]),
                "spread": float(best_ask[0]) - float(best_bid[0]),
                "payload": payload,
            },
        )
        return {
            "candles_saved": candles_saved,
            "trades_saved": trades_saved,
            "orderbooks_saved": 1,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--intervals", default=",".join(SUPPORTED_INTERVALS))
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--sleep", type=float, default=60.0)
    args = parser.parse_args()
    intervals = tuple(item.strip() for item in args.intervals.split(",") if item.strip())
    database = CollectorDatabase(os.getenv("DATABASE_URL", "sqlite:///data/crypto_pipeline.db"))
    collector = BinanceCollector(database)
    try:
        while True:
            print(collector.collect_once(args.symbol, intervals))
            if not args.loop:
                break
            time.sleep(args.sleep)
    finally:
        database.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime

import requests

from .collector_db import CollectorDatabase

SUPPORTED_INTERVALS = ("1m", "3m", "5m", "10m", "15m", "30m")


class BinanceCollector:
    def __init__(self, database: CollectorDatabase) -> None:
        self.database = database
        self.base_url = os.getenv("BINANCE_BASE_URL", "https://api.binance.com/api/v3").rstrip("/")
        self.timeout = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))

    def collect_once(self, symbol: str, intervals: tuple[str, ...]) -> dict[str, int]:
        candles_saved = 0
        for interval in intervals:
            if interval not in SUPPORTED_INTERVALS:
                raise ValueError(f"unsupported interval: {interval}")
            response = requests.get(
                f"{self.base_url}/klines",
                params={"symbol": symbol, "interval": interval, "limit": 200},
                timeout=self.timeout,
            )
            response.raise_for_status()
            rows = [
                {
                    "timestamp": datetime.fromtimestamp(item[0] / 1000),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                }
                for item in response.json()
            ]
            candles_saved += self.database.save_candles("binance", symbol, interval, rows)

        trade_response = requests.get(
            f"{self.base_url}/trades",
            params={"symbol": symbol, "limit": 200},
            timeout=self.timeout,
        )
        trade_response.raise_for_status()
        trades = [
            {
                "trade_id": item["id"],
                "timestamp": datetime.fromtimestamp(item["time"] / 1000),
                "price": float(item["price"]),
                "volume": float(item["qty"]),
                "side": "sell" if item.get("isBuyerMaker") else "buy",
            }
            for item in trade_response.json()
        ]
        trades_saved = self.database.save_trades("binance", symbol, trades)

        book_response = requests.get(
            f"{self.base_url}/depth",
            params={"symbol": symbol, "limit": 20},
            timeout=self.timeout,
        )
        book_response.raise_for_status()
        payload = book_response.json()
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
        return {"candles_saved": candles_saved, "trades_saved": trades_saved, "orderbooks_saved": 1}


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

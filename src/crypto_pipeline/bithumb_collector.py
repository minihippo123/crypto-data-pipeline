from __future__ import annotations

import argparse
import os
import time
from datetime import datetime

import requests

from .collector_db import CollectorDatabase

SUPPORTED_INTERVALS = ("1m", "3m", "5m", "10m", "15m", "30m")
INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30}


class BithumbCollector:
    def __init__(self, database: CollectorDatabase) -> None:
        self.database = database
        self.public_base_url = os.getenv("BITHUMB_PUBLIC_API_BASE_URL", "https://api.bithumb.com/public").rstrip("/")
        self.v1_base_url = os.getenv("BITHUMB_V1_API_BASE_URL", "https://api.bithumb.com/v1").rstrip("/")
        self.timeout = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
        self.session = requests.Session()

    def collect_once(self, symbol: str, intervals: tuple[str, ...]) -> dict[str, int]:
        candles_saved = 0
        for interval in intervals:
            if interval not in SUPPORTED_INTERVALS:
                raise ValueError(f"unsupported interval: {interval}")
            response = self.session.get(
                f"{self.v1_base_url}/candles/minutes/{INTERVAL_MINUTES[interval]}",
                params={"market": f"KRW-{symbol}", "count": 200},
                headers={"accept": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            rows = [
                {
                    "timestamp": datetime.fromisoformat(item["candle_date_time_kst"]),
                    "open": float(item["opening_price"]),
                    "high": float(item["high_price"]),
                    "low": float(item["low_price"]),
                    "close": float(item["trade_price"]),
                    "volume": float(item["candle_acc_trade_volume"]),
                }
                for item in response.json()
            ]
            candles_saved += self.database.save_candles("bithumb", symbol, interval, rows)

        trades_response = self.session.get(
            f"{self.public_base_url}/transaction_history/{symbol}_KRW",
            params={"count": 100},
            timeout=self.timeout,
        )
        trades_response.raise_for_status()
        trades_payload = trades_response.json()
        trades = []
        if trades_payload.get("status") == "0000":
            for index, item in enumerate(trades_payload.get("data", [])):
                timestamp = datetime.strptime(item["transaction_date"], "%Y-%m-%d %H:%M:%S")
                trades.append(
                    {
                        "trade_id": f"{timestamp.isoformat()}-{index}-{item['price']}-{item['units_traded']}",
                        "timestamp": timestamp,
                        "price": float(item["price"]),
                        "volume": float(item["units_traded"]),
                        "side": str(item.get("type", "")).lower() or None,
                    }
                )
        trades_saved = self.database.save_trades("bithumb", symbol, trades)

        book_response = self.session.get(
            f"{self.public_base_url}/orderbook/{symbol}_KRW",
            params={"count": 20},
            timeout=self.timeout,
        )
        book_response.raise_for_status()
        book_payload = book_response.json()
        if book_payload.get("status") != "0000":
            raise RuntimeError(f"Bithumb orderbook error: {book_payload}")
        payload = book_payload["data"]
        best_bid = payload["bids"][0]
        best_ask = payload["asks"][0]
        self.database.save_orderbook(
            "bithumb",
            symbol,
            {
                "timestamp": datetime.fromtimestamp(int(payload["timestamp"]) / 1000),
                "best_bid": float(best_bid["price"]),
                "best_ask": float(best_ask["price"]),
                "bid_volume": float(best_bid["quantity"]),
                "ask_volume": float(best_ask["quantity"]),
                "spread": float(best_ask["price"]) - float(best_bid["price"]),
                "payload": payload,
            },
        )
        return {"candles_saved": candles_saved, "trades_saved": trades_saved, "orderbooks_saved": 1}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--intervals", default=",".join(SUPPORTED_INTERVALS))
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--sleep", type=float, default=60.0)
    args = parser.parse_args()
    intervals = tuple(item.strip() for item in args.intervals.split(",") if item.strip())
    database = CollectorDatabase(os.getenv("DATABASE_URL", "sqlite:///data/crypto_pipeline.db"))
    collector = BithumbCollector(database)
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

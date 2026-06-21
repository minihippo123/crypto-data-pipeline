from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from .bithumb_candle_client import BithumbCandleClient, CandleClientConfig
from .collector_db import CollectorDatabase
from .technical_indicators import calculate_indicators, calculate_orderbook_indicators

SUPPORTED_INTERVALS = ("1m", "3m", "5m", "10m", "15m", "30m")
KST = timezone(timedelta(hours=9))
LOGGER = logging.getLogger(__name__)


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in os.getenv(name, default).split(",") if item.strip())


class BithumbCollector:
    def __init__(self, database: CollectorDatabase) -> None:
        self.database = database
        self.symbols = _csv("BITHUMB_SYMBOLS", "BTC,ETH,XRP,SOL,SUI")
        self.public_base_url = os.getenv(
            "BITHUMB_PUBLIC_API_BASE_URL", "https://api.bithumb.com/public"
        ).rstrip("/")
        self.v1_base_url = os.getenv(
            "BITHUMB_V1_API_BASE_URL", "https://api.bithumb.com/v1"
        ).rstrip("/")
        self.public_timeout = float(os.getenv("BITHUMB_PUBLIC_TIMEOUT_SECONDS", "5"))
        self.error_sleep = float(os.getenv("BITHUMB_ERROR_SLEEP_SECONDS", "5"))
        self.loop_sleep = float(os.getenv("BITHUMB_LOOP_SLEEP_SECONDS", "0.2"))
        self.candle_start_second = int(os.getenv("CANDLE_START_SECOND", "0"))
        self.candle_window_seconds = int(os.getenv("CANDLE_WINDOW_SECONDS", "10"))
        self.candle_tasks_per_loop = max(1, int(os.getenv("CANDLE_TASKS_PER_LOOP", "3")))
        self.depth_enabled = os.getenv("ORDERBOOK_DEPTH_ON", "1").lower() in {"1", "true", "yes", "on"}
        self.depth_levels = 30
        self.session = requests.Session()
        self.candle_client = BithumbCandleClient(
            CandleClientConfig(
                base_url=self.v1_base_url,
                timeout_seconds=float(os.getenv("BITHUMB_CANDLE_TIMEOUT_SECONDS", "10")),
                max_retries=int(os.getenv("BITHUMB_CANDLE_MAX_RETRIES", "3")),
                retry_delay_seconds=float(os.getenv("BITHUMB_CANDLE_RETRY_DELAY_SECONDS", "1")),
                page_size=200,
            ),
            self.session,
        )
        self.last_heartbeat = 0.0
        for symbol in self.symbols:
            self.database.ensure_market_tables("bithumb", symbol)

    def _heartbeat(self) -> None:
        now = time.time()
        if now - self.last_heartbeat >= 300:
            self.database.ping()
            self.database.log_event(
                "bithumb_collector",
                "heartbeat",
                "SUCCESS",
                {"symbols": list(self.symbols)},
            )
            LOGGER.info("BithumbCollector running")
            self.last_heartbeat = now

    @staticmethod
    def intervals_for_minute(minute: int) -> tuple[str, ...]:
        intervals = ["1m"]
        for value in (3, 5, 10, 15, 30):
            if minute % value == 0:
                intervals.append(f"{value}m")
        return tuple(intervals)

    def fetch_orderbook(self, symbol: str) -> dict | None:
        try:
            response = self.session.get(
                f"{self.public_base_url}/orderbook/{symbol}_KRW",
                timeout=self.public_timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "0000":
                return None
            data = payload["data"]
            bids = [
                [float(item["price"]), float(item["quantity"])]
                for item in data.get("bids", [])[: self.depth_levels]
            ]
            asks = [
                [float(item["price"]), float(item["quantity"])]
                for item in data.get("asks", [])[: self.depth_levels]
            ]
            if not bids or not asks:
                return None
            bid_total = sum(item[1] for item in bids)
            ask_total = sum(item[1] for item in asks)
            total = bid_total + ask_total
            row = {
                "timestamp": datetime.fromtimestamp(int(data["timestamp"]) / 1000, tz=timezone.utc)
                .astimezone(KST)
                .replace(tzinfo=None),
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
        except Exception as exc:
            LOGGER.warning("orderbook fetch failed %s: %s", symbol, exc)
            return None

    def fetch_trades(self, symbol: str) -> list[dict]:
        try:
            response = self.session.get(
                f"{self.public_base_url}/transaction_history/{symbol}_KRW",
                timeout=self.public_timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "0000":
                return []
            trades = []
            total_value = 0.0
            total_volume = 0.0
            for item in payload.get("data", []):
                timestamp = datetime.strptime(item["transaction_date"], "%Y-%m-%d %H:%M:%S")
                price = float(item["price"])
                volume = float(item["units_traded"])
                value = price * volume
                total_value += value
                total_volume += volume
                trades.append(
                    {
                        "timestamp": timestamp,
                        "price": price,
                        "volume": volume,
                        "total_value": value,
                        "is_buyer_maker": 1 if item.get("type") == "bid" else 0,
                    }
                )
            vwap = total_value / total_volume if total_volume else 0.0
            for trade in trades:
                trade["vwap"] = vwap
            return trades
        except Exception as exc:
            LOGGER.warning("trade fetch failed %s: %s", symbol, exc)
            return []

    def fetch_candles(self, symbol: str, interval: str, count: int = 5) -> list[dict]:
        result = self.candle_client.fetch_recent(symbol, interval, count)
        if result.status not in {"SUCCESS", "PARTIAL"}:
            self.database.log_event(
                "bithumb_collector",
                "candle_fetch",
                result.status,
                {
                    "symbol": symbol,
                    "interval": interval,
                    "error_type": result.error_type,
                    "error_message": result.error_message,
                },
            )
            return []
        return result.candles

    def calculate_and_save_indicators(self, symbol: str, interval: str) -> bool:
        rows = self.database.get_candles("bithumb", symbol, interval, limit=200)
        result = calculate_indicators(rows)
        if result is None:
            return False
        timestamp, indicators = result
        self.database.save_indicators("bithumb", symbol, interval, timestamp, indicators)
        return True

    def collect_realtime_for_symbol(self, symbol: str) -> dict[str, int]:
        orderbooks = 0
        trades_saved = 0
        orderbook = self.fetch_orderbook(symbol)
        if orderbook:
            self.database.save_orderbook("bithumb", symbol, orderbook)
            if self.depth_enabled:
                self.database.save_orderbook_depth(
                    "bithumb", symbol, orderbook, self.depth_levels
                )
            self.database.save_orderbook_status("bithumb", symbol, orderbook)
            orderbooks = 1
        trades = self.fetch_trades(symbol)
        if trades:
            trades_saved = self.database.save_trades("bithumb", symbol, trades)
        return {"orderbooks_saved": orderbooks, "trades_saved": trades_saved}

    def collect_once(self, intervals: tuple[str, ...] = SUPPORTED_INTERVALS) -> dict[str, int]:
        summary = {
            "candles_saved": 0,
            "indicators_saved": 0,
            "orderbooks_saved": 0,
            "trades_saved": 0,
        }
        for symbol in self.symbols:
            for interval in intervals:
                if interval not in SUPPORTED_INTERVALS:
                    raise ValueError(f"unsupported interval: {interval}")
                candles = self.fetch_candles(symbol, interval, count=200)
                if candles:
                    summary["candles_saved"] += self.database.save_candles(
                        "bithumb", symbol, interval, candles
                    )
                    if self.calculate_and_save_indicators(symbol, interval):
                        summary["indicators_saved"] += 1
            realtime = self.collect_realtime_for_symbol(symbol)
            summary["orderbooks_saved"] += realtime["orderbooks_saved"]
            summary["trades_saved"] += realtime["trades_saved"]
        self.database.log_event("bithumb_collector", "collect_once", "SUCCESS", summary)
        return summary

    def run(self) -> None:
        last_minute = -1
        tasks: list[tuple[str, str, str]] = []
        ready_at: datetime | None = None
        deadline: datetime | None = None
        while True:
            try:
                self._heartbeat()
                now = datetime.now()
                if now.minute != last_minute:
                    last_minute = now.minute
                    tasks = []
                    intervals = self.intervals_for_minute(now.minute)
                    for symbol in self.symbols:
                        for interval in intervals:
                            tasks.append(("candles", symbol, interval))
                        for interval in intervals:
                            tasks.append(("indicators", symbol, interval))
                    minute_start = now.replace(second=0, microsecond=0)
                    ready_at = minute_start + timedelta(seconds=max(0, self.candle_start_second))
                    deadline = ready_at + timedelta(seconds=max(1, self.candle_window_seconds))
                    if now >= deadline:
                        ready_at = now
                        deadline = None

                for _ in range(self.candle_tasks_per_loop):
                    if not tasks:
                        break
                    current = datetime.now()
                    if ready_at and current < ready_at:
                        break
                    if deadline and current >= deadline:
                        deadline = None
                    kind, symbol, interval = tasks.pop(0)
                    if kind == "candles":
                        candles = self.fetch_candles(symbol, interval, count=5)
                        if candles:
                            self.database.save_candles("bithumb", symbol, interval, candles)
                    else:
                        self.calculate_and_save_indicators(symbol, interval)

                if tasks:
                    time.sleep(self.loop_sleep)
                    continue

                for symbol in self.symbols:
                    self.collect_realtime_for_symbol(symbol)
                time.sleep(self.loop_sleep)
            except Exception as exc:
                LOGGER.exception("collector loop failed: %s", exc)
                self.database.log_event(
                    "bithumb_collector", "run_loop", "ERROR", {"error": str(exc)}
                )
                time.sleep(self.error_sleep)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    database = CollectorDatabase(os.getenv("DATABASE_URL", "sqlite:///data/crypto_pipeline.db"))
    collector = BithumbCollector(database)
    try:
        print(collector.collect_once()) if args.once else collector.run()
    finally:
        database.close()


if __name__ == "__main__":
    main()

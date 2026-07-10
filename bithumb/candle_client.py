from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

import requests

LOGGER = logging.getLogger(__name__)

INTERVAL_TO_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
}


def market(symbol: str) -> str:
    symbol = symbol.upper()
    return symbol if symbol.startswith("KRW-") else f"KRW-{symbol}"


def parse_candle(item: Dict) -> Dict:
    return {
        "timestamp": datetime.fromisoformat(item["candle_date_time_kst"]),
        "open": float(item["opening_price"]),
        "high": float(item["high_price"]),
        "low": float(item["low_price"]),
        "close": float(item["trade_price"]),
        "volume": float(item["candle_acc_trade_volume"]),
        "trade_amount": float(item["candle_acc_trade_price"]),
    }


class BithumbCandleClient:
    def __init__(
        self,
        base_url: str = "https://api.bithumb.com/v1",
        timeout_sec: float = 10.0,
        max_retries: int = 3,
        retry_delay_sec: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.retry_delay_sec = retry_delay_sec
        self.session = requests.Session()

    def _get(self, path: str, params: Dict) -> object:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(
                    f"{self.base_url}{path}", params=params, timeout=self.timeout_sec
                )
                if response.status_code == 429:
                    time.sleep(self.retry_delay_sec * attempt)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                LOGGER.warning("Bithumb candle request failed attempt=%s error=%s", attempt, exc)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_sec * attempt)
        raise RuntimeError(f"Bithumb candle request failed: {last_error}")

    def fetch_recent(self, symbol: str, interval: str, count: int = 200) -> List[Dict]:
        minutes = INTERVAL_TO_MINUTES[interval]
        payload = self._get(
            f"/candles/minutes/{minutes}",
            {"market": market(symbol), "count": min(int(count), 200)},
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected Bithumb payload: {type(payload).__name__}")
        rows = [parse_candle(item) for item in payload]
        rows.sort(key=lambda row: row["timestamp"])
        return rows

    def fetch_range(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        delay_sec: float = 0.2,
    ) -> List[Dict]:
        minutes = INTERVAL_TO_MINUTES[interval]
        step = timedelta(minutes=minutes)
        cursor = end.replace(tzinfo=None)
        output: Dict[datetime, Dict] = {}
        while cursor >= start:
            expected = int((cursor - start).total_seconds() // step.total_seconds()) + 1
            count = min(expected, 200)
            payload = self._get(
                f"/candles/minutes/{minutes}",
                {
                    "market": market(symbol),
                    "count": count,
                    "to": (cursor + step).strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
            if not isinstance(payload, list) or not payload:
                break
            parsed = [parse_candle(item) for item in payload]
            for row in parsed:
                if start <= row["timestamp"] <= end:
                    output[row["timestamp"]] = row
            oldest = min(row["timestamp"] for row in parsed)
            if oldest <= start:
                break
            cursor = oldest - step
            time.sleep(delay_sec)
        return [output[key] for key in sorted(output)]

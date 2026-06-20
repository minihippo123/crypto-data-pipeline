from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

import requests

from .models import Candle


class CandleSource(Protocol):
    def fetch_range(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[Candle]: ...


class HttpCandleSource:
    """Generic public-API adapter.

    The endpoint must return either a JSON list or a JSON object containing a
    ``data`` list. Field mapping is intentionally generic and contains no
    account credentials, private endpoints, or production host information.
    """

    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        if not base_url:
            raise ValueError("SOURCE_API_BASE_URL is required for HTTP backfill")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_range(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[Candle]:
        response = requests.get(
            f"{self.base_url}/candles",
            params={
                "symbol": symbol,
                "interval": interval,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("source response must contain a list of candles")
        return [_parse_candle(symbol, interval, item) for item in rows]


def _parse_candle(symbol: str, interval: str, item: dict) -> Candle:
    return Candle(
        symbol=symbol,
        interval=interval,
        timestamp=datetime.fromisoformat(str(item["timestamp"])),
        open=Decimal(str(item["open"])),
        high=Decimal(str(item["high"])),
        low=Decimal(str(item["low"])),
        close=Decimal(str(item["close"])),
        volume=Decimal(str(item.get("volume", 0))),
    )

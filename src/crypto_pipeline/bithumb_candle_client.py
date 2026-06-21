from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

KST = timezone(timedelta(hours=9))
INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30}


@dataclass(frozen=True, slots=True)
class CandleClientConfig:
    base_url: str = "https://api.bithumb.com/v1"
    timeout_seconds: float = 10.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    page_size: int = 200


@dataclass(frozen=True, slots=True)
class CandleFetchResult:
    status: str
    candles: list[dict]
    attempts: int
    http_status: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    raw_rows: int = 0
    duplicate_rows: int = 0
    out_of_range_rows: int = 0


class BithumbCandleClient:
    def __init__(self, config: CandleClientConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def fetch_recent(self, symbol: str, interval: str, count: int = 5) -> CandleFetchResult:
        self._validate_interval(interval)
        return self._request(
            symbol,
            interval,
            {"market": f"KRW-{symbol.upper()}", "count": int(count)},
        )

    def fetch_range(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> CandleFetchResult:
        self._validate_interval(interval)
        if end < start:
            return CandleFetchResult("EMPTY", [], 0, error_type="EMPTY_RANGE")

        step = timedelta(minutes=INTERVAL_MINUTES[interval])
        start = self._kst_naive(start)
        end = self._kst_naive(end)
        cursor = end
        rows: dict[datetime, dict] = {}
        attempts = 0
        raw_rows = 0
        duplicate_rows = 0
        out_of_range_rows = 0
        last_http_status = None

        while cursor >= start:
            remaining = int((cursor - start) / step) + 1
            page = self._request(
                symbol,
                interval,
                {
                    "market": f"KRW-{symbol.upper()}",
                    "count": min(self.config.page_size, remaining),
                    "to": (cursor + step).strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
            attempts += page.attempts
            raw_rows += page.raw_rows
            last_http_status = page.http_status
            if page.status != "SUCCESS":
                return CandleFetchResult(
                    "PARTIAL" if rows else page.status,
                    sorted(rows.values(), key=lambda item: item["timestamp"]),
                    attempts,
                    last_http_status,
                    page.error_type,
                    page.error_message,
                    raw_rows,
                    duplicate_rows,
                    out_of_range_rows,
                )
            if not page.candles:
                break
            page_min = min(item["timestamp"] for item in page.candles)
            for candle in page.candles:
                timestamp = candle["timestamp"]
                if timestamp < start or timestamp > end:
                    out_of_range_rows += 1
                    continue
                if timestamp in rows:
                    duplicate_rows += 1
                    continue
                rows[timestamp] = candle
            if page_min <= start:
                break
            cursor = page_min - step

        candles = sorted(rows.values(), key=lambda item: item["timestamp"])
        expected = int((end - start) / step) + 1
        status = "SUCCESS" if len(candles) >= expected else "PARTIAL" if candles else "EMPTY"
        return CandleFetchResult(
            status,
            candles,
            attempts,
            last_http_status,
            None if status == "SUCCESS" else status,
            None if status == "SUCCESS" else f"Fetched {len(candles)}/{expected}",
            raw_rows,
            duplicate_rows,
            out_of_range_rows,
        )

    def _request(self, symbol: str, interval: str, params: dict[str, Any]) -> CandleFetchResult:
        endpoint = INTERVAL_MINUTES[interval]
        url = f"{self.config.base_url.rstrip('/')}/candles/minutes/{endpoint}"
        last_error: Exception | None = None
        last_status = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers={"accept": "application/json"},
                    timeout=self.config.timeout_seconds,
                )
                last_status = response.status_code
                if response.status_code == 429:
                    if attempt < self.config.max_retries:
                        time.sleep(self._retry_delay(attempt, response))
                        continue
                    return CandleFetchResult("RATE_LIMITED", [], attempt, response.status_code, "RATE_LIMITED", "Bithumb rate limit")
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    message = str(payload.get("error") or payload)
                    return CandleFetchResult("API_ERROR", [], attempt, response.status_code, "API_ERROR", message)
                if not isinstance(payload, list):
                    return CandleFetchResult("INVALID_RESPONSE", [], attempt, response.status_code, "UNEXPECTED_PAYLOAD", type(payload).__name__)
                candles = [self._parse(item, interval) for item in payload]
                unique = {item["timestamp"]: item for item in candles}
                rows = sorted(unique.values(), key=lambda item: item["timestamp"])
                return CandleFetchResult(
                    "SUCCESS" if rows else "EMPTY",
                    rows,
                    attempt,
                    response.status_code,
                    raw_rows=len(payload),
                    duplicate_rows=len(payload) - len(rows),
                )
            except requests.Timeout as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                return CandleFetchResult("TIMEOUT", [], attempt, last_status, "TIMEOUT", str(exc))
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
        return CandleFetchResult("HTTP_ERROR", [], self.config.max_retries, last_status, type(last_error).__name__ if last_error else "UNKNOWN", str(last_error))

    def _parse(self, item: dict, interval: str) -> dict:
        timestamp = datetime.fromisoformat(str(item["candle_date_time_kst"]))
        return {
            "timestamp": timestamp.replace(tzinfo=None),
            "candle_interval": interval,
            "open": float(item["opening_price"]),
            "high": float(item["high_price"]),
            "low": float(item["low_price"]),
            "close": float(item["trade_price"]),
            "volume": float(item["candle_acc_trade_volume"]),
            "trade_amount": float(item.get("candle_acc_trade_price", 0)),
        }

    def _retry_delay(self, attempt: int, response=None) -> float:
        if response is not None:
            header = response.headers.get("Retry-After")
            if header:
                try:
                    return float(header)
                except ValueError:
                    pass
        return self.config.retry_delay_seconds * attempt

    @staticmethod
    def _kst_naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(KST).replace(tzinfo=None)

    @staticmethod
    def _validate_interval(interval: str) -> None:
        if interval not in INTERVAL_MINUTES:
            raise ValueError(f"unsupported interval: {interval}")

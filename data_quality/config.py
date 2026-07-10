from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List

DEFAULT_BITHUMB_SYMBOLS = ["BTC", "ETH", "XRP", "SOL", "SUI"]
DEFAULT_BITHUMB_INTERVALS = ["1m", "3m", "5m", "10m", "15m", "30m"]


def env_list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def parse_freshness(raw: str | None = None) -> Dict[str, int]:
    defaults = {"1m": 5, "3m": 10, "5m": 15, "10m": 20, "15m": 30, "30m": 60}
    if not raw:
        return defaults
    values = dict(defaults)
    for item in raw.split(","):
        if not item.strip() or ":" not in item:
            continue
        key, value = item.split(":", 1)
        values[key.strip()] = int(value.strip())
    return values


@dataclass
class DataQualityConfig:
    default_mode: str = "auto"
    incremental_lookback_hours: int = 12
    deep_lookback_days: int = 7
    chunk_days_1m: int = 1
    chunk_days_default: int = 7
    repair_enabled: bool = True
    max_backfill_retries: int = 3
    api_request_delay_sec: float = 0.2
    api_timeout_sec: float = 10.0
    api_count_per_request: int = 200
    lock_timeout_minutes: int = 120
    indicator_warmup_candles: int = 120
    indicator_dependency_candles: int = 200
    indicator_recalc_limit_per_dataset: int = 5000
    indicator_batch_size: int = 500
    indicator_queue_stale_minutes: int = 120
    indicator_queue_max_attempts: int = 3
    bithumb_symbols: List[str] = field(default_factory=lambda: list(DEFAULT_BITHUMB_SYMBOLS))
    bithumb_intervals: List[str] = field(default_factory=lambda: list(DEFAULT_BITHUMB_INTERVALS))
    freshness_minutes: Dict[str, int] = field(default_factory=parse_freshness)
    public_timeout_sec: float = 5.0
    candle_timeout_sec: float = 10.0
    public_api_base_url: str = "https://api.bithumb.com/public"
    v1_api_base_url: str = "https://api.bithumb.com/v1"

    @classmethod
    def from_env(cls) -> "DataQualityConfig":
        return cls(
            default_mode=os.getenv("DQ_DEFAULT_MODE", "auto").strip().lower(),
            incremental_lookback_hours=env_int("DQ_INCREMENTAL_LOOKBACK_HOURS", 12),
            deep_lookback_days=env_int("DQ_DEEP_LOOKBACK_DAYS", 7),
            chunk_days_1m=env_int("DQ_CHUNK_DAYS_1M", env_int("DQ_CHUNK_DAYS", 1)),
            chunk_days_default=env_int("DQ_CHUNK_DAYS_DEFAULT", env_int("DQ_CHUNK_DAYS", 7)),
            repair_enabled=env_bool("DQ_REPAIR_ENABLED", True),
            max_backfill_retries=env_int("DQ_MAX_BACKFILL_RETRIES", 3),
            api_request_delay_sec=env_float("DQ_API_REQUEST_DELAY_SEC", 0.2),
            api_timeout_sec=env_float("DQ_API_TIMEOUT_SEC", 10.0),
            api_count_per_request=env_int("DQ_API_COUNT_PER_REQUEST", 200),
            lock_timeout_minutes=env_int("DQ_LOCK_TIMEOUT_MINUTES", 120),
            indicator_warmup_candles=env_int("DQ_INDICATOR_WARMUP_CANDLES", 120),
            indicator_dependency_candles=max(env_int("DQ_INDICATOR_WARMUP_CANDLES", 120), env_int("DQ_INDICATOR_DEPENDENCY_CANDLES", 200)),
            indicator_recalc_limit_per_dataset=env_int("DQ_INDICATOR_RECALC_LIMIT_PER_DATASET", 5000),
            indicator_batch_size=env_int("DQ_INDICATOR_BATCH_SIZE", 500),
            indicator_queue_stale_minutes=env_int("DQ_INDICATOR_QUEUE_STALE_MINUTES", 120),
            indicator_queue_max_attempts=env_int("DQ_INDICATOR_QUEUE_MAX_ATTEMPTS", 3),
            bithumb_symbols=env_list("BITHUMB_SYMBOLS", DEFAULT_BITHUMB_SYMBOLS),
            bithumb_intervals=env_list("DQ_BITHUMB_INTERVALS", DEFAULT_BITHUMB_INTERVALS),
            freshness_minutes=parse_freshness(os.getenv("DQ_FRESHNESS_MINUTES")),
            public_timeout_sec=env_float("BITHUMB_PUBLIC_TIMEOUT_SEC", 5.0),
            candle_timeout_sec=env_float("BITHUMB_CANDLE_TIMEOUT_SEC", 10.0),
            public_api_base_url=os.getenv("BITHUMB_PUBLIC_API_BASE_URL", "https://api.bithumb.com/public").rstrip("/"),
            v1_api_base_url=os.getenv("BITHUMB_V1_API_BASE_URL", "https://api.bithumb.com/v1").rstrip("/"),
        )

    def chunk_days_for_interval(self, interval: str) -> int:
        return self.chunk_days_1m if interval == "1m" else self.chunk_days_default

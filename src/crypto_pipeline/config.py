from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    source_api_base_url: str
    source_api_timeout_seconds: float
    demo_symbols: tuple[str, ...]
    demo_intervals: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv(
                "DATABASE_URL", "sqlite:///data/crypto_pipeline_demo.sqlite3"
            ),
            source_api_base_url=os.getenv("SOURCE_API_BASE_URL", ""),
            source_api_timeout_seconds=float(
                os.getenv("SOURCE_API_TIMEOUT_SECONDS", "10")
            ),
            demo_symbols=_csv("DEMO_SYMBOLS", "BTC,ETH"),
            demo_intervals=_csv(
                "DEMO_INTERVALS", "1m,3m,5m,10m,15m,30m"
            ),
        )


def _csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(
        item.strip().upper() if name == "DEMO_SYMBOLS" else item.strip()
        for item in raw.split(",")
        if item.strip()
    )

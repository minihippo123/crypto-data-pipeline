from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    interval: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.high < max(self.open, self.close, self.low):
            errors.append("high_below_ohlc")
        if self.low > min(self.open, self.close, self.high):
            errors.append("low_above_ohlc")
        if min(self.open, self.high, self.low, self.close, self.volume) < 0:
            errors.append("negative_value")
        return errors


@dataclass(frozen=True, slots=True)
class Gap:
    symbol: str
    interval: str
    start: datetime
    end: datetime
    expected_count: int


@dataclass(frozen=True, slots=True)
class AuditEvent:
    run_id: str
    stage: str
    status: str
    occurred_at: datetime
    details: dict[str, object]

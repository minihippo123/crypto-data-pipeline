from datetime import datetime, timedelta
from decimal import Decimal

from crypto_pipeline.models import Candle
from crypto_pipeline.quality import detect_gaps, detect_invalid


def candle(minute: int, high: str = "102", low: str = "99") -> Candle:
    return Candle(
        symbol="DEMO",
        interval="1m",
        timestamp=datetime(2026, 1, 1) + timedelta(minutes=minute),
        open=Decimal("100"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal("101"),
        volume=Decimal("1"),
    )


def test_detects_missing_range() -> None:
    gaps = detect_gaps([candle(0), candle(3)])
    assert len(gaps) == 1
    assert gaps[0].expected_count == 2


def test_detects_invalid_ohlc() -> None:
    findings = detect_invalid([candle(0, high="100")])
    assert findings

from decimal import Decimal

from .models import Candle
from .repository import SQLiteRepository


def recalculate_sma3(repository: SQLiteRepository, candles: list[Candle]) -> int:
    closes: list[Decimal] = []
    for candle in candles:
        closes.append(candle.close)
        value = sum(closes[-3:]) / 3 if len(closes) >= 3 else None
        repository.upsert_sma3(candle, value)
    return len(candles)

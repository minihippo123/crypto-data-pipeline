from datetime import datetime, timedelta

from crypto_pipeline.bithumb_collector import BithumbCollector
from crypto_pipeline.technical_indicators import calculate_indicators


def test_interval_schedule_matches_production_rules() -> None:
    assert BithumbCollector.intervals_for_minute(1) == ("1m",)
    assert BithumbCollector.intervals_for_minute(10) == ("1m", "5m", "10m")
    assert BithumbCollector.intervals_for_minute(15) == ("1m", "3m", "5m", "15m")
    assert BithumbCollector.intervals_for_minute(30) == (
        "1m",
        "3m",
        "5m",
        "10m",
        "15m",
        "30m",
    )


def test_full_indicator_set_is_calculated_after_warmup() -> None:
    start = datetime(2026, 1, 1)
    rows = []
    for index in range(140):
        price = 100.0 + index * 0.1 + (index % 7) * 0.03
        rows.append(
            {
                "timestamp": (start + timedelta(minutes=index)).isoformat(),
                "open_price": price - 0.2,
                "high_price": price + 0.5,
                "low_price": price - 0.5,
                "close_price": price,
                "volume": 10.0 + index % 9,
            }
        )

    result = calculate_indicators(rows)

    assert result is not None
    _, indicators = result
    expected = {
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_hist",
        "ma_5",
        "ma_15",
        "ma_20",
        "ma_60",
        "ma_120",
        "upper_band",
        "lower_band",
        "stochastic_k",
        "stochastic_d",
        "ema_3",
        "ema_5",
        "ema_10",
        "ema_20",
        "cci_14",
        "mfi_14",
        "roc_10",
        "vwap_value",
        "momentum_10",
        "adx_value",
        "atr_value",
        "obv_value",
        "rsi_divergence",
        "macd_divergence",
    }
    assert expected.issubset(indicators)

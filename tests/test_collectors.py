from datetime import datetime, timedelta

from crypto_pipeline.account_collector import AccountCollector
from crypto_pipeline.binance_collector import BinanceCollector


def test_binance_10m_aggregation() -> None:
    start = datetime(2026, 1, 1, 0, 0)
    rows = [
        {
            "timestamp": start,
            "open": 100.0,
            "high": 103.0,
            "low": 99.0,
            "close": 102.0,
            "volume": 1.0,
        },
        {
            "timestamp": start + timedelta(minutes=5),
            "open": 102.0,
            "high": 105.0,
            "low": 101.0,
            "close": 104.0,
            "volume": 2.0,
        },
    ]

    result = BinanceCollector._aggregate_10m(rows)

    assert result == [
        {
            "timestamp": start,
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 104.0,
            "volume": 3.0,
        }
    ]


def test_account_authorization_changes_per_request(monkeypatch) -> None:
    monkeypatch.setenv("ACCOUNT_ACCESS_VALUE", "public-id")
    monkeypatch.setenv("ACCOUNT_SIGNING_VALUE", "runtime-only-value")

    collector = object.__new__(AccountCollector)
    collector.access_value = "public-id"
    collector.signing_value = "runtime-only-value"

    first = collector._authorization_header()["Authorization"]
    second = collector._authorization_header()["Authorization"]

    assert first.startswith("Bearer ")
    assert second.startswith("Bearer ")
    assert first != second

from datetime import datetime, timedelta

from crypto_pipeline.collector_db import CollectorDatabase


def _orderbook(timestamp: datetime) -> dict:
    bids = [[100.0 - index, 1.0 + index] for index in range(30)]
    asks = [[101.0 + index, 1.5 + index] for index in range(30)]
    bid_total = sum(quantity for _, quantity in bids)
    ask_total = sum(quantity for _, quantity in asks)
    total = bid_total + ask_total
    return {
        "timestamp": timestamp,
        "bid_price": bids[0][0],
        "bid_volume": bids[0][1],
        "ask_price": asks[0][0],
        "ask_volume": asks[0][1],
        "bid_total_volume": bid_total,
        "ask_total_volume": ask_total,
        "spread": 1.0,
        "book_imbalance": bid_total / ask_total,
        "bid_imbalance": bid_total / total,
        "ask_imbalance": ask_total / total,
        "imbalance_ratio": (bid_total - ask_total) / total,
        "orderbook_pressure": 0.1,
        "spread_pct": 1.0,
        "vwap_5": 100.5,
        "liquidity_density": total,
        "bids_levels": bids,
        "asks_levels": asks,
    }


def test_production_side_effects_are_preserved(tmp_path) -> None:
    database = CollectorDatabase(f"sqlite:///{tmp_path / 'collector.sqlite3'}")
    timestamp = datetime(2026, 1, 1)
    candle = {
        "timestamp": timestamp,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 2.0,
        "trade_amount": 202.0,
    }

    database.save_candles("bithumb", "BTC", "1m", [candle])
    database.save_candles("bithumb", "BTC", "1m", [{**candle, "close": 103.0}])

    rows = database.get_candles("bithumb", "BTC", "1m")
    assert len(rows) == 1
    assert rows[0]["close_price"] == 103.0

    trade = {
        "timestamp": timestamp,
        "price": 100.0,
        "volume": 2.0,
        "total_value": 200.0,
        "is_buyer_maker": 1,
        "vwap": 100.0,
    }
    assert database.save_trades("bithumb", "BTC", [trade]) == 1
    assert database.save_trades("bithumb", "BTC", [trade]) == 0

    orderbook = _orderbook(timestamp + timedelta(seconds=1))
    database.save_orderbook("bithumb", "BTC", orderbook)
    database.save_orderbook_depth("bithumb", "BTC", orderbook, 30)
    database.save_orderbook_status("bithumb", "BTC", orderbook)

    depth_count = database.connection.execute(
        "SELECT COUNT(*) FROM bithumb_btc_orderbook_levels"
    ).fetchone()[0]
    assert depth_count == 61

    status_count = database.connection.execute(
        "SELECT COUNT(*) FROM symbol_orderbook_status WHERE exchange='bithumb' AND symbol='BTC'"
    ).fetchone()[0]
    assert status_count == 1

    database.save_indicators(
        "bithumb",
        "BTC",
        "1m",
        timestamp,
        {"rsi_14": 50.0},
    )
    indicator_count = database.connection.execute(
        "SELECT COUNT(*) FROM bithumb_btc_i_1m_indicators"
    ).fetchone()[0]
    assert indicator_count == 1
    database.close()

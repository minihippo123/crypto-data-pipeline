from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("open_price", "high_price", "low_price", "close_price", "volume")


def calculate_indicators(rows: list[dict]) -> tuple[datetime, dict] | None:
    if not rows:
        return None
    frame = pd.DataFrame(rows)
    if frame.empty or any(column not in frame for column in REQUIRED_COLUMNS):
        return None
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    for column in REQUIRED_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.rename(
        columns={
            "open_price": "open",
            "high_price": "high",
            "low_price": "low",
            "close_price": "close",
        }
    )

    frame["ma_5"] = frame["close"].rolling(5).mean()
    frame["ma_15"] = frame["close"].rolling(15).mean()
    frame["ma_20"] = frame["close"].rolling(20).mean()
    frame["ma_60"] = frame["close"].rolling(60).mean()
    frame["ma_120"] = frame["close"].rolling(120).mean()
    frame["volume_ma_5"] = frame["volume"].rolling(5).mean()
    frame["volume_ma_20"] = frame["volume"].rolling(20).mean()
    frame["volume_ma_120"] = frame["volume"].rolling(120).mean()

    std_20 = frame["close"].rolling(20).std()
    frame["upper_band"] = frame["ma_20"] + std_20 * 2
    frame["lower_band"] = frame["ma_20"] - std_20 * 2
    frame["bandwidth"] = (frame["upper_band"] - frame["lower_band"]) / frame["ma_20"] * 100

    low_14 = frame["low"].rolling(14).min()
    high_14 = frame["high"].rolling(14).max()
    frame["stochastic_k"] = (frame["close"] - low_14) / (high_14 - low_14) * 100
    frame["stochastic_d"] = frame["stochastic_k"].rolling(3).mean()

    delta = frame["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    frame["rsi_14"] = 100 - 100 / (1 + rs)

    ema_12 = frame["close"].ewm(span=12, adjust=False).mean()
    ema_26 = frame["close"].ewm(span=26, adjust=False).mean()
    frame["macd"] = ema_12 - ema_26
    frame["macd_signal"] = frame["macd"].ewm(span=9, adjust=False).mean()
    frame["macd_hist"] = frame["macd"] - frame["macd_signal"]
    for period in (3, 5, 10, 20):
        frame[f"ema_{period}"] = frame["close"].ewm(span=period, adjust=False).mean()

    typical_price = (frame["high"] + frame["low"] + frame["close"]) / 3
    typical_mean = typical_price.rolling(14).mean()
    mean_deviation = typical_price.rolling(14).apply(
        lambda values: np.mean(np.abs(values - np.mean(values))), raw=True
    )
    frame["cci_14"] = (typical_price - typical_mean) / (0.015 * mean_deviation)

    money_flow = typical_price * frame["volume"]
    direction = typical_price.diff()
    positive = money_flow.where(direction > 0, 0).rolling(14).sum()
    negative = money_flow.where(direction < 0, 0).rolling(14).sum()
    frame["mfi_14"] = 100 - 100 / (1 + positive / negative)

    frame["roc_10"] = frame["close"].pct_change(10) * 100
    frame["volume_change_pct"] = frame["volume"].pct_change() * 100
    frame["vwap_value"] = (frame["close"] * frame["volume"]).cumsum() / frame["volume"].cumsum()
    frame["momentum_10"] = (frame["close"] - frame["close"].shift(10)) / frame["close"].shift(10) * 100

    frame["vol_ratio_5"] = (frame["volume"] / frame["volume_ma_5"].replace(0, np.nan)).fillna(1.0)
    frame["vol_ratio_20"] = (frame["volume"] / frame["volume_ma_20"].replace(0, np.nan)).fillna(1.0)
    frame["vol_ratio_120"] = (frame["volume"] / frame["volume_ma_120"].replace(0, np.nan)).fillna(1.0)
    frame["rvol_spike"] = (frame["vol_ratio_120"] >= 3.0).astype(int)

    candle_range = (frame["high"] - frame["low"]).replace(0, np.nan)
    frame["body_ratio"] = ((frame["close"] - frame["open"]).abs() / candle_range).fillna(0.0)
    frame["upper_wick"] = ((frame["high"] - frame[["open", "close"]].max(axis=1)) / candle_range).fillna(0.0)
    frame["lower_wick"] = ((frame[["open", "close"]].min(axis=1) - frame["low"]) / candle_range).fillna(0.0)

    price_direction = np.sign(frame["close"].pct_change(5))
    rsi_direction = np.sign(frame["rsi_14"].diff(5))
    macd_direction = np.sign(frame["macd_hist"].diff(5))
    frame["rsi_divergence"] = np.where(
        (price_direction < 0) & (rsi_direction > 0), 1,
        np.where((price_direction > 0) & (rsi_direction < 0), -1, 0),
    )
    frame["macd_divergence"] = np.where(
        (price_direction < 0) & (macd_direction > 0), 1,
        np.where((price_direction > 0) & (macd_direction < 0), -1, 0),
    )

    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr_value"] = true_range.rolling(14).mean()

    previous_high = frame["high"].shift(1)
    previous_low = frame["low"].shift(1)
    plus_dm = np.where(
        (frame["high"] - previous_high > previous_low - frame["low"])
        & (frame["high"] - previous_high > 0),
        frame["high"] - previous_high,
        0,
    )
    minus_dm = np.where(
        (previous_low - frame["low"] > frame["high"] - previous_high)
        & (previous_low - frame["low"] > 0),
        previous_low - frame["low"],
        0,
    )
    atr = true_range.rolling(14).mean()
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    frame["adx_value"] = dx.rolling(14).mean()

    obv_change = np.where(delta > 0, frame["volume"], np.where(delta < 0, -frame["volume"], 0))
    frame["obv_value"] = pd.Series(obv_change).cumsum()

    latest = frame.iloc[-1]
    required = [
        "rsi_14", "macd", "macd_signal", "macd_hist", "ma_5", "ma_15", "ma_20",
        "ma_60", "ma_120", "volume_ma_5", "volume_ma_20", "upper_band", "lower_band",
        "bandwidth", "stochastic_k", "stochastic_d", "ema_3", "ema_5", "ema_10",
        "ema_20", "cci_14", "mfi_14", "roc_10", "volume_change_pct", "vwap_value",
        "momentum_10",
    ]
    if latest[required].isna().any():
        return None

    fields = required + [
        "adx_value", "atr_value", "obv_value", "vol_ratio_5", "vol_ratio_20",
        "vol_ratio_120", "rvol_spike", "body_ratio", "upper_wick", "lower_wick",
        "rsi_divergence", "macd_divergence",
    ]
    indicators = {
        field: (
            int(latest[field])
            if field in {"rvol_spike", "rsi_divergence", "macd_divergence"}
            else float(latest[field])
            if pd.notna(latest[field])
            else 0.0
        )
        for field in fields
    }
    timestamp = pd.to_datetime(latest["timestamp"]).to_pydatetime().replace(tzinfo=None)
    return timestamp, indicators


def calculate_orderbook_indicators(orderbook: dict) -> dict:
    bid_price = float(orderbook["bid_price"])
    ask_price = float(orderbook["ask_price"])
    bid_total = float(orderbook["bid_total_volume"])
    ask_total = float(orderbook["ask_total_volume"])
    spread = ask_price - bid_price
    total_volume = bid_total + ask_total
    weighted_total = bid_price * bid_total + ask_price * ask_total
    return {
        "imbalance_ratio": (bid_total - ask_total) / total_volume if total_volume else 0.0,
        "spread_pct": spread / bid_price * 100 if bid_price else 0.0,
        "vwap_5": weighted_total / total_volume if total_volume else 0.0,
        "liquidity_density": total_volume / spread if spread > 0 else 0.0,
        "orderbook_pressure": (bid_price * bid_total - ask_price * ask_total) / weighted_total if weighted_total else 0.0,
    }

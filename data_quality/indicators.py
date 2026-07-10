from __future__ import annotations


def calculate_basic_indicators(rows: list[dict]) -> dict:
    if len(rows) < 20:
        return {}
    closes = [float(row.get("close_price", row.get("close", 0))) for row in rows]
    volumes = [float(row.get("volume", 0)) for row in rows]
    return {
        "ma_5": sum(closes[-5:]) / 5,
        "ma_20": sum(closes[-20:]) / 20,
        "volume_ma_5": sum(volumes[-5:]) / 5,
        "volume_ma_20": sum(volumes[-20:]) / 20,
    }

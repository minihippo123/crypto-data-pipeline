INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30}


def interval_minutes(interval: str) -> int:
    return INTERVAL_MINUTES[interval]

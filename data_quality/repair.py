from __future__ import annotations

from bithumb.candle_client import BithumbCandleClient


def repair_bithumb_range(symbol: str, interval: str, start, end, config):
    client = BithumbCandleClient(
        base_url=config.v1_api_base_url,
        timeout_sec=config.candle_timeout_sec,
        max_retries=config.max_backfill_retries,
        retry_delay_sec=config.api_request_delay_sec,
    )
    return client.fetch_range(symbol, interval, start, end, config.api_request_delay_sec)

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Engine


def identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]", "_", value.lower()).strip("_")
    if not cleaned:
        raise ValueError(f"invalid identifier: {value}")
    return f"i_{cleaned}" if cleaned[0].isdigit() else cleaned


def execute_ddl(engine: Engine, statements: list[str]) -> None:
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_global_tables(engine: Engine) -> None:
    execute_ddl(
        engine,
        [
            """
            CREATE TABLE IF NOT EXISTS symbol_orderbook_status (
                exchange VARCHAR(32) NOT NULL,
                symbol VARCHAR(32) NOT NULL,
                timestamp DATETIME(6) NOT NULL,
                current_price DECIMAL(30,10) NOT NULL,
                bid_price DECIMAL(30,10) NOT NULL,
                ask_price DECIMAL(30,10) NOT NULL,
                spread DECIMAL(30,10) NOT NULL,
                bid_volume DECIMAL(38,18) NOT NULL,
                ask_volume DECIMAL(38,18) NOT NULL,
                bid_total_volume DECIMAL(38,18) NOT NULL,
                ask_total_volume DECIMAL(38,18) NOT NULL,
                book_imbalance DECIMAL(30,10) NOT NULL,
                bid_imbalance DECIMAL(30,10) NOT NULL,
                ask_imbalance DECIMAL(30,10) NOT NULL,
                imbalance_ratio DECIMAL(30,10) NOT NULL,
                orderbook_pressure DECIMAL(30,10) NOT NULL,
                spread_pct DECIMAL(30,10) NOT NULL,
                vwap_5 DECIMAL(30,10) NOT NULL,
                liquidity_density DECIMAL(30,10) NOT NULL,
                PRIMARY KEY (exchange, symbol)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS collector_events (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                collector VARCHAR(64) NOT NULL,
                event_type VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                occurred_at DATETIME(6) NOT NULL,
                details_json LONGTEXT NOT NULL,
                PRIMARY KEY (id),
                KEY idx_collector_events_time (occurred_at),
                KEY idx_collector_events_status (collector, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS data_quality_runs (
                run_id VARCHAR(64) NOT NULL,
                stage VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                occurred_at DATETIME(6) NOT NULL,
                details_json LONGTEXT NOT NULL,
                PRIMARY KEY (run_id, stage, occurred_at),
                KEY idx_dq_runs_time (occurred_at),
                KEY idx_dq_runs_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS indicator_recalc_queue (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                exchange VARCHAR(32) NOT NULL,
                symbol VARCHAR(32) NOT NULL,
                candle_interval VARCHAR(8) NOT NULL,
                affected_start DATETIME(6) NOT NULL,
                affected_end DATETIME(6) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                attempts INT NOT NULL DEFAULT 0,
                error_message TEXT NULL,
                created_at DATETIME(6) NOT NULL,
                updated_at DATETIME(6) NOT NULL,
                PRIMARY KEY (id),
                KEY idx_recalc_queue_work
                  (status, exchange, symbol, candle_interval, affected_start)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        ],
    )


def ensure_market_tables(engine: Engine, exchange: str, symbol: str) -> None:
    prefix = f"{identifier(exchange)}_{identifier(symbol)}"
    execute_ddl(
        engine,
        [
            f"""
            CREATE TABLE IF NOT EXISTS `{prefix}_candles` (
                timestamp DATETIME(6) NOT NULL,
                candle_interval VARCHAR(8) NOT NULL,
                open_price DECIMAL(30,10) NOT NULL,
                high_price DECIMAL(30,10) NOT NULL,
                low_price DECIMAL(30,10) NOT NULL,
                close_price DECIMAL(30,10) NOT NULL,
                volume DECIMAL(38,18) NOT NULL,
                trade_amount DECIMAL(38,10) NOT NULL DEFAULT 0,
                PRIMARY KEY (timestamp, candle_interval),
                KEY idx_{prefix}_candles_interval_time
                  (candle_interval, timestamp)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            f"""
            CREATE TABLE IF NOT EXISTS `{prefix}_trades` (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                timestamp DATETIME(6) NOT NULL,
                price DECIMAL(30,10) NOT NULL,
                volume DECIMAL(38,18) NOT NULL,
                total_value DECIMAL(38,10) NOT NULL,
                is_buyer_maker TINYINT(1) NOT NULL,
                vwap DECIMAL(30,10) NOT NULL,
                PRIMARY KEY (id),
                UNIQUE KEY uq_{prefix}_trade
                  (timestamp, price, volume, total_value, is_buyer_maker),
                KEY idx_{prefix}_trades_time (timestamp)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            f"""
            CREATE TABLE IF NOT EXISTS `{prefix}_orderbooks` (
                timestamp DATETIME(6) NOT NULL,
                bid_price DECIMAL(30,10) NOT NULL,
                bid_volume DECIMAL(38,18) NOT NULL,
                ask_price DECIMAL(30,10) NOT NULL,
                ask_volume DECIMAL(38,18) NOT NULL,
                bid_total_volume DECIMAL(38,18) NOT NULL,
                ask_total_volume DECIMAL(38,18) NOT NULL,
                spread DECIMAL(30,10) NOT NULL,
                book_imbalance DECIMAL(30,10) NOT NULL,
                bid_imbalance DECIMAL(30,10) NOT NULL,
                ask_imbalance DECIMAL(30,10) NOT NULL,
                imbalance_ratio DECIMAL(30,10) NOT NULL,
                orderbook_pressure DECIMAL(30,10) NOT NULL,
                spread_pct DECIMAL(30,10) NOT NULL,
                vwap_5 DECIMAL(30,10) NOT NULL,
                liquidity_density DECIMAL(30,10) NOT NULL,
                PRIMARY KEY (timestamp)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            f"""
            CREATE TABLE IF NOT EXISTS `{prefix}_orderbook_levels` (
                level SMALLINT NOT NULL,
                side VARCHAR(8) NOT NULL,
                price DECIMAL(30,10) NOT NULL,
                quantity DECIMAL(38,18) NOT NULL,
                total DECIMAL(38,10) NOT NULL,
                current_price DECIMAL(30,10) NOT NULL,
                timestamp DATETIME(6) NOT NULL,
                PRIMARY KEY (level),
                KEY idx_{prefix}_orderbook_levels_time (timestamp)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
        ],
    )


def ensure_indicator_table(
    engine: Engine, exchange: str, symbol: str, interval: str
) -> str:
    table = (
        f"{identifier(exchange)}_{identifier(symbol)}_"
        f"{identifier(interval)}_indicators"
    )
    execute_ddl(
        engine,
        [
            f"""
            CREATE TABLE IF NOT EXISTS `{table}` (
                timestamp DATETIME(6) NOT NULL,
                payload_json LONGTEXT NOT NULL,
                PRIMARY KEY (timestamp)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        ],
    )
    return table

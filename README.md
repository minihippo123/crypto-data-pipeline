# Crypto Data Pipeline

A public, executable version of a cryptocurrency data collection and data-quality system.

## What actually runs

This repository contains three collector services:

- `bithumb_collector`: fetches public candles, trades, and orderbook snapshots from Bithumb
- `binance_collector`: fetches public candles, trades, and orderbook snapshots from Binance
- `account_collector`: fetches private account balances when a runtime authorization header is supplied

Collected data is stored in a local SQLite database at `data/crypto_pipeline.db`.

Supported candle intervals are exactly:

```text
1m, 3m, 5m, 10m, 15m, 30m
```

`1h` is not supported.

## Run the collectors

Bithumb once:

```bash
python -m crypto_pipeline.bithumb_collector \
  --symbol BTC \
  --intervals 1m,3m,5m,10m,15m,30m
```

Binance once:

```bash
python -m crypto_pipeline.binance_collector \
  --symbol BTCUSDT \
  --intervals 1m,3m,5m,10m,15m,30m
```

Run both public collectors continuously with Docker:

```bash
docker compose -f docker-compose.collectors.yml up --build
```

Run only one collector:

```bash
docker compose -f docker-compose.collectors.yml up --build bithumb-collector
```

## Account collector

The account collector calls the real private account endpoint and stores a timestamped account snapshot. No key, password, token, or authorization value is committed to this repository.

Supply a valid runtime request-header JSON value through `ACCOUNT_REQUEST_HEADERS_JSON`, then run:

```bash
docker compose -f docker-compose.collectors.yml \
  --profile private-account up --build account-collector
```

## Stored tables

- `market_candles`
- `market_trades`
- `orderbook_snapshots`
- `account_snapshots`

All tables are created automatically.

## Data-quality workflow

The repository also includes the data-quality core:

```text
Collect -> Validate -> Detect -> Repair -> Recalculate -> Revalidate -> Audit
```

It detects candle gaps, duplicates, and invalid OHLCV data, supports repair through a source adapter, recalculates indicators, and records audit events.

## Security and privacy

This public repository intentionally contains no production-specific information:

- no database passwords, usernames, or private connection strings
- no API keys, signing keys, tokens, or account credentials
- no private IP addresses or hostnames
- no NAS paths or deployment details
- no production database names
- no personal identifiers

All private runtime values must be injected through environment variables and must never be committed.

# Crypto Data Pipeline

An executable portfolio project for collecting cryptocurrency market data, validating its integrity, repairing source-backed gaps, and rebuilding dependent technical indicators.

The repository is intentionally sanitized. It contains no credentials, private infrastructure identifiers, production database names, account balances, trading strategies, or personal information.

## What this project demonstrates

- resilient public-market data collection
- interval-aware candle scheduling and storage
- duplicate prevention and idempotent upserts
- OHLCV validity checks
- missing-candle detection across large time ranges
- source-backed gap repair with revalidation
- durable indicator-recalculation queues
- overlapping-range merge before batch recalculation
- technical-indicator rebuild with warm-up windows
- persistent audit evidence for every quality-control stage
- Docker-based local execution and automated tests

## Pipeline

```text
Public exchange APIs
        │
        ▼
Collectors ──> Raw market tables ──> Technical indicators
        │               │                     │
        │               ▼                     │
        └────────> Data-quality scan           │
                        │                     │
                        ├─ completeness        │
                        ├─ uniqueness          │
                        ├─ validity            │
                        ▼                     │
                  Source-backed repair         │
                        │                     │
                        ▼                     │
              Indicator impact-range queue ───┘
                        │
                        ▼
              Merge overlapping ranges
                        │
                        ▼
              Batch indicator recalculation
                        │
                        ▼
                 Revalidation + audit
```

## Data-quality lifecycle

```text
Collect
  -> Validate
  -> Detect
  -> Repair
  -> Queue dependent work
  -> Merge impact ranges
  -> Recalculate indicators
  -> Revalidate
  -> Persist audit evidence
```

The repair process is conservative:

- only candles returned for the exact requested timestamp range are accepted
- unrelated API rows are discarded
- partially repaired ranges remain unresolved
- only fully revalidated candle ranges are queued for indicator recalculation
- failed indicator ranges remain visible for retry and investigation

## Supported market data

### Bithumb

- candles: `1m`, `3m`, `5m`, `10m`, `15m`, `30m`
- trades
- order-book snapshots
- derived order-book metrics
- technical indicators

### Binance

- candles
- trades
- order-book snapshots
- derived depth data
- technical indicators
- 10-minute candle aggregation from native 5-minute candles

The public project uses configurable symbol lists and public endpoints only.

## Storage model

The portfolio version uses SQLite for reproducibility. Tables are separated by exchange, symbol, and interval to preserve the operational behavior of a larger relational deployment.

```text
{exchange}_{symbol}_candles
{exchange}_{symbol}_trades
{exchange}_{symbol}_orderbooks
{exchange}_{symbol}_orderbook_levels
{exchange}_{symbol}_{interval}_indicators

collector_events
audit_events
indicator_recalc_queue
```

## Indicator recalculation queue

A repaired candle can affect indicators beyond the repaired timestamp because rolling calculations depend on prior observations.

The queue stores an affected range and processes it with a warm-up window.

```text
PENDING -> RUNNING -> SUCCESS
                   └-> FAILED
```

Before processing, overlapping or adjacent ranges are merged. This avoids recalculating the same rows repeatedly when many nearby candle gaps are repaired.

## Run locally

```bash
cp .env.example .env
python -m pip install -e '.[dev]'
pytest -q
```

Run one public collection cycle:

```bash
bithumb-collector --once
binance-collector --once
```

Run continuously:

```bash
bithumb-collector
binance-collector
```

Run a local data-quality demonstration with synthetic data:

```bash
crypto-pipeline --demo --repair
```

## Run with Docker

Start the public collectors:

```bash
docker compose up --build bithumb-collector binance-collector
```

Run the quality pipeline:

```bash
docker compose --profile quality run --rm quality-pipeline
```

## Quality controls

| Control | Purpose | Evidence |
|---|---|---|
| Completeness | Detect missing interval timestamps | gap findings and remaining-missing counts |
| Uniqueness | Prevent duplicate candles and trades | primary keys, deduplication, conflict counts |
| Validity | Check OHLCV relationships and values | invalid-row findings |
| Repair authorization | Restore only exact source-backed rows | requested range and accepted rows |
| Dependency control | Recalculate indicators after candle changes | durable queue and warm-up range |
| Revalidation | Confirm the issue was actually resolved | remaining-gap and status fields |
| Auditability | Preserve run and stage outcomes | persistent audit records |

## Tests

The automated test suite covers:

- interval scheduling through 30 minutes
- candle upsert idempotency
- duplicate-trade prevention
- order-book depth storage
- Binance 10-minute aggregation
- technical-indicator calculation after warm-up
- missing-candle detection
- source-backed repair
- partial and unrecoverable repair outcomes
- indicator queue creation and range merging
- recalculation and revalidation

## Repository boundaries

This repository is a standalone public implementation designed for review and reproduction. It does not include or connect to any private deployment.

Excluded by design:

- real access values or signing values
- private infrastructure and machine-specific paths
- private database identifiers
- production datasets or account activity
- personal identifiers

See [docs/architecture.md](docs/architecture.md) and [docs/data-quality.md](docs/data-quality.md) for the design details.
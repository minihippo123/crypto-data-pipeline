# Crypto Data Pipeline

A sanitized, executable portfolio version of a cryptocurrency collection and data-quality system operated in a private environment.

The public repository removes credentials and infrastructure identifiers while preserving the collectors' operational behavior.

## Architecture

```text
Bithumb public APIs ─┐
                     ├─> collectors ─> per-symbol tables ─> indicators
Binance public APIs ─┘                         │
                                              ├─> duplicate prevention
Private account API ─> account collector ─────┤
                                              └─> collector event log

Collected candles ─> validate ─> detect gaps ─> repair ─> recalculate ─> audit
```

## Collectors

### Bithumb collector

The public Bithumb collector preserves the production collector's main behavior:

- multiple symbols in one process
- `1m`, `3m`, `5m`, `10m`, `15m`, and `30m` candle scheduling
- resilient candle client with retry and rate-limit handling
- candle upsert by timestamp and interval
- trade collection, batch VWAP, and duplicate prevention
- orderbook snapshots and derived orderbook indicators
- fixed 61-row depth ladder: 30 bids, midpoint, and 30 asks
- latest per-symbol orderbook status
- technical-indicator calculation and interval-specific storage
- heartbeat events and continuous collection loop

### Binance collector

The Binance collector preserves the corresponding operational flow:

- multiple symbols
- trades, candles, and orderbook collection
- per-symbol timestamp deduplication
- retry and HTTP 429 handling
- 10-minute candle generation from two native 5-minute candles
- per-symbol candle, trade, orderbook, depth, and indicator storage
- heartbeat and continuous execution

### Account collector

The account collector:

- creates a new nonce and timestamp for every request
- signs a new JWT for every account API call
- retrieves available and locked balances
- fetches public prices for non-cash assets
- calculates total account valuation
- stores timestamped balance snapshots
- runs at a configurable collection interval with heartbeat and error logging

No access value, signing value, password, token, or authorization header is committed.

## Supported intervals

```text
1m, 3m, 5m, 10m, 15m, 30m
```

`1h` is intentionally unsupported.

## Storage model

The public version uses SQLite so that reviewers can run it without access to a private database server.

For each exchange and symbol, the collector creates tables equivalent to the private collector's operational effects:

```text
{exchange}_{symbol}_candles
{exchange}_{symbol}_trades
{exchange}_{symbol}_orderbooks
{exchange}_{symbol}_orderbook_levels
{exchange}_{symbol}_{interval}_indicators
```

Shared tables:

```text
symbol_orderbook_status
account_snapshots
collector_events
```

## Run locally

```bash
cp .env.example .env
python -m pip install -e '.[dev]'
pytest -q
```

Run one complete public collection cycle:

```bash
bithumb-collector --once
binance-collector --once
```

Run continuously:

```bash
bithumb-collector
binance-collector
```

Run the account collector after providing private runtime values only in the local environment:

```bash
account-collector --once
```

## Run with Docker

Run both public market collectors continuously:

```bash
docker compose up --build bithumb-collector binance-collector
```

Run the private account collector only when its local environment values are configured:

```bash
docker compose --profile private-account up --build account-collector
```

Run the data-quality component:

```bash
docker compose --profile quality run --rm quality-pipeline
```

## Data-quality controls

```text
Collect -> Validate -> Detect -> Repair -> Recalculate -> Revalidate -> Audit
```

Implemented controls include:

- completeness: missing candle timestamp detection
- uniqueness: database keys and trade duplicate prevention
- validity: OHLCV relationship checks
- controlled repair: source-backed candle restoration
- dependent processing: technical-indicator recalculation
- evidence: persistent collector and audit events

## Tests

The tests verify:

- interval scheduling through 30 minutes
- Binance 10-minute aggregation
- account authorization refresh for each request
- candle upsert behavior
- duplicate trade prevention
- fixed 61-row orderbook depth storage
- orderbook status upsert
- interval-specific indicator table creation
- full technical-indicator calculation after warm-up
- end-to-end data-quality repair and revalidation

## Security and privacy

This repository intentionally excludes:

- database usernames and passwords
- API access and signing values
- tokens and authorization headers
- private IP addresses and hostnames
- NAS paths and private deployment details
- private database names
- personal identifiers

All sensitive runtime values must be injected locally through environment variables and must never be committed.

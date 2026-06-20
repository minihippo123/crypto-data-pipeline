# Crypto Data Pipeline

Public portfolio project for an auditable cryptocurrency market-data pipeline.

## Workflow

```text
Collect -> Validate -> Detect -> Repair -> Recalculate -> Revalidate -> Audit
```

## What is included

- Generic candle domain model
- Gap, duplicate, and invalid OHLCV detection
- Credential-free HTTP source adapter
- Idempotent SQLite upsert flow
- Indicator recalculation
- Post-repair validation
- Persistent audit events
- CLI entry point
- Docker and Docker Compose setup
- Unit tests

## Security and privacy

This repository intentionally excludes all production-specific information.

- No API keys or account secrets
- No database passwords or usernames
- No private IP addresses or hostnames
- No NAS paths or deployment details
- No production database or table names
- No personal identifiers
- No private exchange endpoints

All runtime values are supplied through environment variables. The checked-in `.env.example` contains placeholders only.

## Quick start

```bash
cp .env.example .env
python -m pip install -e '.[dev]'
pytest
crypto-pipeline --symbol BTC --interval 1m
```

Docker:

```bash
docker compose build
docker compose run --rm pipeline --symbol BTC --interval 1m
```

To enable repair against a compatible public candle API, set `SOURCE_API_BASE_URL` and add `--repair`.

## Status

The public core has been initialized. Additional demo fixtures, documentation, and CI will be added incrementally.

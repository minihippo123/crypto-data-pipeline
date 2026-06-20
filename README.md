# Crypto Data Pipeline

Public portfolio project for an auditable cryptocurrency market-data pipeline.

## Workflow

```text
Collect -> Validate -> Detect -> Repair -> Recalculate -> Revalidate -> Audit
```

## Goals

- Detect missing, duplicate, stale, and invalid candle data
- Repair missing data from a source API
- Recalculate dependent indicators
- Revalidate repaired data
- Preserve an audit trail
- Run locally with Docker and safe demo data

## Status

Work in progress.

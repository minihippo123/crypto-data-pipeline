# Architecture

## Components

```text
Public exchange APIs
        |
        v
Collectors
  - candle scheduler
  - trade collector
  - order-book collector
  - retry and rate-limit handling
        |
        v
SQLite storage
  - market tables
  - indicator tables
  - collector events
        |
        v
Data-quality manager
  - completeness scan
  - duplicate detection
  - OHLCV validation
  - exact-range repair
  - revalidation
        |
        v
Indicator queue
  - durable status
  - overlapping-range merge
  - warm-up calculation
  - batch upsert
        |
        v
Audit and final dataset status
```

## Design choices

### Public endpoints only

The executable portfolio path relies on public market endpoints. No private account access is required to demonstrate collection, validation, repair, or recalculation.

### SQLite for reproducibility

SQLite keeps the project self-contained for reviewers while preserving relational constraints, idempotent writes, and persistent audit evidence.

### Interval-aware processing

Candles are stored and validated using the expected step for each supported interval. A missing timestamp is evaluated relative to that interval rather than against a universal one-minute rule.

### Conservative repair

The source response is filtered against the exact requested time range. Unrelated rows are ignored, partial repairs remain visible, and dependent work is scheduled only after candle revalidation succeeds.

### Durable dependent work

Indicator recalculation is represented as stored queue records rather than transient in-memory callbacks. This allows retry, failure analysis, restart recovery, and auditable status transitions.

### Range merging

Closely spaced candle repairs can affect the same rolling-indicator window. Adjacent and overlapping ranges are merged before calculation to reduce repeated work.

### Warm-up windows

Indicators such as moving averages, volatility measures, and momentum features require earlier candles. The processor fetches an earlier warm-up range but writes only the affected output rows.

## Public boundary

The repository contains a standalone implementation and generic configuration. It does not contain private deployment topology, private data, account activity, or machine-specific configuration.
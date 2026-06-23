# Data-quality control design

## Objective

The data-quality component verifies that collected market data is complete, unique, valid, repairable, and traceable.

It is designed around one rule: a repair is not considered successful until the affected range has been revalidated.

## Processing stages

### 1. Scan

For every exchange, symbol, and interval, the scanner evaluates a bounded time range and records:

- rows checked
- missing timestamp ranges
- missing candle count
- duplicate rows
- invalid OHLCV rows
- indicator gaps
- indicator rows without a matching candle
- indicator-value anomalies

Large ranges are scanned in smaller windows so progress and partial results remain visible.

### 2. Candle repair

Each detected gap is requested from the configured public source.

A returned candle is accepted only when its timestamp is inside the requested range. Rows outside the range are counted and discarded.

Possible outcomes:

| Status | Meaning |
|---|---|
| `SUCCESS` | The requested range was fully restored and revalidated |
| `PARTIAL` | Some rows were restored but at least one timestamp is still missing |
| `UNRECOVERABLE` | The source did not return a usable row for the requested range |
| `FAILED` | The request, write, or validation process failed |

Partial repairs may write valid rows, but they are not treated as complete repairs.

### 3. Revalidation

The repaired range is scanned again.

Only a range with no remaining expected timestamp gap is eligible for dependent indicator processing.

### 4. Indicator impact queue

Successful candle repairs create durable indicator-recalculation work.

Each queue item contains:

- exchange
- symbol
- interval
- affected start and end
- status
- attempt count
- error details
- created, started, and completed timestamps

Queue states:

```text
PENDING -> RUNNING -> SUCCESS
                   └-> FAILED
```

Interrupted `RUNNING` items can be returned to a retryable state. Failed items remain available for review rather than disappearing from the audit trail.

### 5. Range merge

Nearby candle repairs frequently produce overlapping indicator impact windows.

Before recalculation, overlapping and directly adjacent queue ranges are merged. Superseded items remain traceable while only the merged range is processed.

This reduces redundant reads, calculations, and database writes.

### 6. Indicator recalculation

Rolling indicators require earlier candles. The processor therefore reads a warm-up window before the affected range, calculates the full feature set, and writes only the requested output range.

The operation records:

- fetched candle count
- calculated row count
- inserted rows
- updated rows
- elapsed time
- final status

### 7. Final reporting

A dataset can finish with:

- `SUCCESS`: no unresolved control issue remains
- `PARTIAL`: useful repairs succeeded but unresolved gaps or failed indicator ranges remain
- `FAILED`: the dataset could not be processed reliably

A `PARTIAL` result is intentional. It prevents incomplete repairs from being presented as full success.

## Audit evidence

The public implementation retains structured evidence for:

- run configuration
- scan results
- source fetch outcomes
- discarded out-of-range rows
- rows inserted or updated
- candle revalidation
- queue creation and merge
- indicator recalculation
- unresolved errors

Sensitive request headers and credentials are never written to the audit records.

## Interpretation of missing candles

A missing interval in a local table is not automatically proof of collector failure.

Possible causes include:

- a collection outage
- an exchange API limitation
- an exchange-side data omission
- a period with no trade-generated candle

The pipeline reports the observable condition and repair result. A higher-level operational analysis can compare the timestamp against trade data to classify the root cause.
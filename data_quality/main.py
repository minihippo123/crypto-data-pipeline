from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta

from .candles import find_gap_ranges
from .config import DataQualityConfig
from .db import Database
from .failures import FailureReason, classify_exception
from .migrations import apply_migrations
from .models import Dataset, RunStats
from .notifications import DataQualityNotifier
from .repository import DataQualityRepository


def build_dataset(symbol: str, interval: str) -> Dataset:
    lower = symbol.lower()
    return Dataset(
        id=None,
        source="bithumb",
        symbol=symbol,
        interval=interval,
        candle_table=f"bithumb_{lower}_candles",
        indicator_table=f"bithumb_{lower}_{interval}_indicators",
    )


def _mode_window(mode: str, config: DataQualityConfig, now: datetime) -> tuple[datetime, datetime]:
    if mode == "full":
        return datetime(2020, 1, 1), now
    if mode == "deep":
        return now - timedelta(days=config.deep_lookback_days), now
    return now - timedelta(hours=config.incremental_lookback_hours), now


def _table_exists(db: Database, table: str) -> bool:
    return db.table_exists(table)


def _fetch_candle_rows(db: Database, table: str, interval: str, start: datetime, end: datetime) -> list[dict]:
    return db.fetchall(
        f"""
        SELECT timestamp, `open`, high, low, `close`, volume
        FROM {table}
        WHERE `interval`=%s AND timestamp BETWEEN %s AND %s
        ORDER BY timestamp
        """,
        (interval, start, end),
    )


def _count_invalid_candles(rows: list[dict]) -> int:
    invalid = 0
    for row in rows:
        try:
            open_price = float(row["open"])
            high_price = float(row["high"])
            low_price = float(row["low"])
            close_price = float(row["close"])
            volume = float(row["volume"])
            if low_price > high_price:
                invalid += 1
            elif not (low_price <= open_price <= high_price and low_price <= close_price <= high_price):
                invalid += 1
            elif volume < 0:
                invalid += 1
        except Exception:
            invalid += 1
    return invalid


def _indicator_table_status(db: Database, table: str) -> tuple[str, str | None]:
    if not _table_exists(db, table):
        return "FAILED", FailureReason.INDICATOR_TABLE_MISSING.value
    return "SUCCESS", None


def _critical_thresholds() -> dict[str, int]:
    return {
        "gaps": int(os.getenv("DQ_ALERT_GAP_RANGES", "1")),
        "invalid_rows": int(os.getenv("DQ_ALERT_INVALID_ROWS", "1")),
        "unresolved_errors": int(os.getenv("DQ_ALERT_UNRESOLVED_ERRORS", "1")),
    }


def _issue_payload(summary: dict, extra: dict | None = None) -> dict:
    payload = {
        "gap_ranges": summary.get("gap_ranges", 0),
        "missing_candles": summary.get("missing_candles", 0),
        "invalid_rows": summary.get("invalid_rows", 0),
        "indicator_status": summary.get("indicator_status", "UNKNOWN"),
    }
    if extra:
        payload.update(extra)
    return payload


def analyze_dataset(
    db: Database,
    repo: DataQualityRepository,
    notifier: DataQualityNotifier,
    run_id: str,
    dataset: Dataset,
    dataset_label: str,
    start: datetime,
    end: datetime,
) -> dict:
    summary = {
        "gap_ranges": 0,
        "missing_candles": 0,
        "invalid_rows": 0,
        "indicator_status": "UNKNOWN",
        "failure_reason": None,
    }
    if not _table_exists(db, dataset.candle_table):
        repo.record_check(
            run_id,
            dataset.id,
            "CANDLE_TABLE",
            "FAILED",
            start,
            end,
            affected_rows=1,
            failure_reason=FailureReason.DB_TABLE_MISSING.value,
            details={"table": dataset.candle_table, "action": "run collector or create market table"},
        )
        summary["failure_reason"] = FailureReason.DB_TABLE_MISSING.value
        notifier.issue(
            run_id,
            dataset_label,
            "CANDLE_TABLE",
            FailureReason.DB_TABLE_MISSING.value,
            {"table": dataset.candle_table, "action": "run collector or create market table"},
        )
        return summary

    rows = _fetch_candle_rows(db, dataset.candle_table, dataset.interval, start, end)
    timestamps = [row["timestamp"] for row in rows]
    gaps = find_gap_ranges(timestamps, dataset.interval)
    invalid_rows = _count_invalid_candles(rows)
    summary["gap_ranges"] = len(gaps)
    summary["missing_candles"] = sum(
        max(1, int((gap_end - gap_start).total_seconds() // 60))
        for gap_start, gap_end in gaps
    )
    summary["invalid_rows"] = invalid_rows

    if gaps:
        details = {
            "gap_ranges": len(gaps),
            "missing_candles": summary["missing_candles"],
            "sample": [(str(gap_start), str(gap_end)) for gap_start, gap_end in gaps[:10]],
            "meaning": "local DB has missing interval timestamps; backfill/revalidation required",
        }
        repo.record_check(
            run_id,
            dataset.id,
            "CANDLE_COMPLETENESS",
            "FAILED",
            start,
            end,
            expected_value=None,
            actual_value=len(rows),
            affected_rows=len(gaps),
            failure_reason=FailureReason.LOCAL_CANDLE_GAP.value,
            details=details,
        )
        summary["failure_reason"] = FailureReason.LOCAL_CANDLE_GAP.value
        notifier.issue(run_id, dataset_label, "CANDLE_COMPLETENESS", FailureReason.LOCAL_CANDLE_GAP.value, details)
        for gap_start, gap_end in gaps[: int(os.getenv("DQ_ALERT_GAP_SAMPLE_LIMIT", "10"))]:
            notifier.issue(
                run_id,
                dataset_label,
                "CANDLE_GAP_SAMPLE",
                FailureReason.LOCAL_CANDLE_GAP.value,
                {"range_start": gap_start, "range_end": gap_end, "action": "backfill then revalidate this exact range"},
            )
    else:
        repo.record_check(
            run_id,
            dataset.id,
            "CANDLE_COMPLETENESS",
            "SUCCESS",
            start,
            end,
            actual_value=len(rows),
            affected_rows=0,
            details={"rows": len(rows)},
        )

    if invalid_rows:
        details = {"invalid_rows": invalid_rows, "meaning": "OHLCV rule violation or unparsable values"}
        repo.record_check(
            run_id,
            dataset.id,
            "CANDLE_VALIDITY",
            "FAILED",
            start,
            end,
            affected_rows=invalid_rows,
            failure_reason=FailureReason.LOCAL_INVALID_CANDLE.value,
            details=details,
        )
        summary["failure_reason"] = FailureReason.LOCAL_INVALID_CANDLE.value
        notifier.issue(run_id, dataset_label, "CANDLE_VALIDITY", FailureReason.LOCAL_INVALID_CANDLE.value, details)
    else:
        repo.record_check(
            run_id,
            dataset.id,
            "CANDLE_VALIDITY",
            "SUCCESS",
            start,
            end,
            affected_rows=0,
            details={"invalid_rows": 0},
        )

    indicator_status, indicator_reason = _indicator_table_status(db, dataset.indicator_table)
    summary["indicator_status"] = indicator_status
    if indicator_status != "SUCCESS":
        details = {"table": dataset.indicator_table, "meaning": "indicator recalculation cannot write/read target table"}
        repo.record_check(
            run_id,
            dataset.id,
            "INDICATOR_TABLE",
            "FAILED",
            start,
            end,
            affected_rows=1,
            failure_reason=indicator_reason,
            details=details,
        )
        if summary["failure_reason"] is None:
            summary["failure_reason"] = indicator_reason
        notifier.issue(run_id, dataset_label, "INDICATOR_TABLE", indicator_reason or "UNKNOWN", details)
    else:
        repo.record_check(
            run_id,
            dataset.id,
            "INDICATOR_TABLE",
            "SUCCESS",
            start,
            end,
            affected_rows=0,
            details={"table": dataset.indicator_table},
        )

    return summary


def run(mode: str) -> dict:
    config = DataQualityConfig.from_env()
    db = Database.from_env()
    notifier = DataQualityNotifier()
    try:
        apply_migrations(db)
        repo = DataQualityRepository(db)
        started_at = datetime.now().replace(microsecond=0)
        start, end = _mode_window(mode, config, started_at)
        run_id = repo.create_run(mode, started_at)
        datasets = [build_dataset(symbol, interval) for symbol in config.bithumb_symbols for interval in config.bithumb_intervals]
        stats = RunStats()
        thresholds = _critical_thresholds()
        notifier.started(run_id, mode, len(datasets), config.repair_enabled)

        for index, raw_dataset in enumerate(datasets, start=1):
            dataset_label = f"{raw_dataset.source} {raw_dataset.symbol} {raw_dataset.interval}"
            notifier.dataset_started(run_id, dataset_label, index, len(datasets))
            try:
                dataset = repo.upsert_dataset(raw_dataset)
                stats.datasets_checked += 1
                summary = analyze_dataset(db, repo, notifier, run_id, dataset, dataset_label, start, end)
                dataset_failed = bool(summary.get("failure_reason"))
                if dataset_failed:
                    stats.checks_failed += 1
                    stats.unresolved_errors += int(summary["gap_ranges"] or 0) + int(summary["invalid_rows"] or 0) + (1 if summary.get("indicator_status") != "SUCCESS" else 0)
                else:
                    stats.checks_passed += 1
                stats.gaps_detected += int(summary["gap_ranges"] or 0)
                notifier.dataset_completed(run_id, dataset_label, "PARTIAL" if dataset_failed else "SUCCESS", summary)
                if summary["gap_ranges"] >= thresholds["gaps"] or summary["invalid_rows"] >= thresholds["invalid_rows"] or stats.unresolved_errors >= thresholds["unresolved_errors"]:
                    notifier.critical(run_id, f"Dataset threshold exceeded: {dataset_label}", _issue_payload(summary, {"total_unresolved_errors": stats.unresolved_errors}))
                notifier.progress(run_id, stats, dataset_label)
            except Exception as exc:
                classified = classify_exception(exc)
                stats.datasets_checked += 1
                stats.checks_failed += 1
                stats.unresolved_errors += 1
                try:
                    dataset = repo.upsert_dataset(raw_dataset)
                    repo.record_check(
                        run_id,
                        dataset.id,
                        "DATASET_EXCEPTION",
                        "FAILED",
                        start,
                        end,
                        affected_rows=1,
                        failure_reason=classified.reason.value,
                        details={"error": classified.message, "operator_action": classified.operator_action},
                    )
                finally:
                    notifier.issue(
                        run_id,
                        dataset_label,
                        "DATASET_EXCEPTION",
                        classified.reason.value,
                        {"error": classified.message, "action": classified.operator_action},
                    )
                    notifier.critical(
                        run_id,
                        f"Dataset exception: {dataset_label}",
                        {"reason": classified.reason.value, "error": classified.message, "action": classified.operator_action},
                    )
                    notifier.progress(run_id, stats, dataset_label)

        status = "SUCCESS" if stats.checks_failed == 0 and stats.unresolved_errors == 0 else "PARTIAL"
        repo.finish_run(run_id, datetime.now(), status, stats)
        notifier.final(
            run_id,
            status,
            stats,
            repo.failure_reason_summary(run_id),
            repo.dataset_issue_summary(run_id),
            repo.failure_samples(run_id),
            repo.indicator_queue_summary(run_id),
        )
        return {"run_id": run_id, "status": status, "datasets_checked": stats.datasets_checked, "unresolved_errors": stats.unresolved_errors}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="auto", choices=("auto", "incremental", "deep", "full"))
    args = parser.parse_args()
    print(run(args.mode))


if __name__ == "__main__":
    main()

from datetime import datetime, timedelta

from data_quality.db import Database
from data_quality.failures import FailureReason
from data_quality.migrations import apply_migrations
from data_quality.models import Dataset, RunStats
from data_quality.repository import DataQualityRepository


def main():
    db = Database.from_env()
    try:
        if db.dialect != "mysql":
            raise AssertionError(f"expected mysql dialect, got {db.dialect}")
        apply_migrations(db)
        apply_migrations(db)
        for table in (
            "dq_dataset_registry",
            "dq_scan_runs",
            "dq_check_results",
            "dq_backfill_jobs",
            "dq_recalculation_jobs",
            "dq_locks",
            "dq_indicator_recalc_queue",
        ):
            if not db.table_exists(table):
                raise AssertionError(f"missing table: {table}")

        repo = DataQualityRepository(db)
        now = datetime.now().replace(microsecond=0)
        dataset = repo.upsert_dataset(
            Dataset(
                id=None,
                source="bithumb",
                symbol="PUBLIC_TEST",
                interval="1m",
                candle_table="bithumb_public_test_candles",
                indicator_table="bithumb_public_test_1m_indicators",
            )
        )
        run_id = repo.create_run("integration", now)
        repo.record_check(
            run_id,
            dataset.id,
            "BACKFILL",
            "FAILED",
            now - timedelta(minutes=3),
            now,
            expected_value=3,
            actual_value=0,
            affected_rows=3,
            failure_reason=FailureReason.SOURCE_NO_DATA.value,
            details={"sample": "source returned zero candles"},
        )
        queue_id = repo.enqueue_indicator_recalc(run_id, dataset, now - timedelta(minutes=3), now)
        repo.mark_indicator_queue_failed(
            queue_id,
            FailureReason.MISSING_WARMUP_CANDLES.value,
            "not enough warmup candles",
        )
        reason_summary = repo.failure_reason_summary(run_id)
        if not reason_summary or reason_summary[0]["failure_reason"] != FailureReason.SOURCE_NO_DATA.value:
            raise AssertionError("failure reason summary did not classify SOURCE_NO_DATA")
        queue_summary = repo.indicator_queue_summary(run_id)
        if not queue_summary or queue_summary[0]["failure_reason"] != FailureReason.MISSING_WARMUP_CANDLES.value:
            raise AssertionError("indicator queue reason summary failed")
        repo.finish_run(run_id, datetime.now(), "PARTIAL", RunStats(datasets_checked=1, checks_failed=1, unresolved_errors=1))
        row = db.fetchone("SELECT status FROM dq_scan_runs WHERE run_id=%s", (run_id,))
        if row["status"] != "PARTIAL":
            raise AssertionError("run status persistence failed")
        print("MariaDB failure reason integration: SUCCESS")
    finally:
        db.close()


if __name__ == "__main__":
    main()

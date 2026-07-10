from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from .db import Database
from .models import Dataset, IndicatorQueueItem, RunStats


class DataQualityRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_dataset(self, dataset: Dataset) -> Dataset:
        self.db.execute(
            """
            INSERT INTO dq_dataset_registry
              (source, symbol, `interval`, candle_table, indicator_table,
               actual_first_timestamp, actual_last_timestamp)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              candle_table=VALUES(candle_table),
              indicator_table=VALUES(indicator_table),
              actual_first_timestamp=VALUES(actual_first_timestamp),
              actual_last_timestamp=VALUES(actual_last_timestamp)
            """,
            (
                dataset.source,
                dataset.symbol,
                dataset.interval,
                dataset.candle_table,
                dataset.indicator_table,
                dataset.actual_first_timestamp,
                dataset.actual_last_timestamp,
            ),
        )
        row = self.db.fetchone(
            "SELECT * FROM dq_dataset_registry WHERE source=%s AND symbol=%s AND `interval`=%s",
            (dataset.source, dataset.symbol, dataset.interval),
        )
        return Dataset(
            id=row["id"],
            source=row["source"],
            symbol=row["symbol"],
            interval=row["interval"],
            candle_table=row["candle_table"],
            indicator_table=row["indicator_table"],
            actual_first_timestamp=row.get("actual_first_timestamp"),
            actual_last_timestamp=row.get("actual_last_timestamp"),
        )

    def create_run(self, mode: str, started_at: datetime) -> str:
        run_id = f"dq-{started_at.strftime('%Y%m%d-%H%M%S')}"
        self.db.execute(
            """
            INSERT INTO dq_scan_runs (run_id, mode, started_at, status)
            VALUES (%s, %s, %s, 'RUNNING')
            """,
            (run_id, mode.upper(), started_at),
        )
        return run_id

    def record_check(
        self,
        run_id: str,
        dataset_id: int,
        check_type: str,
        status: str,
        range_start,
        range_end,
        expected_value=None,
        actual_value=None,
        affected_rows: int = 0,
        details: dict | None = None,
        failure_reason: str | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO dq_check_results
              (run_id,dataset_id,check_type,status,failure_reason,range_start,range_end,
               expected_value,actual_value,affected_rows,details_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                run_id,
                dataset_id,
                check_type,
                status,
                failure_reason,
                range_start,
                range_end,
                expected_value,
                actual_value,
                affected_rows,
                json.dumps(details or {}, sort_keys=True, default=str),
            ),
        )

    def enqueue_indicator_recalc(self, run_id: str, dataset: Dataset, start, end) -> int:
        self.db.execute(
            """
            INSERT INTO dq_indicator_recalc_queue
              (run_id,dataset_id,affected_start,affected_end,status)
            VALUES (%s,%s,%s,%s,'PENDING')
            """,
            (run_id, dataset.id, start, end),
        )
        row = self.db.fetchone("SELECT LAST_INSERT_ID() AS id")
        return int(row["id"])

    def mark_indicator_queue_failed(self, queue_id: int, reason: str, error_message: str) -> None:
        self.db.execute(
            """
            UPDATE dq_indicator_recalc_queue
            SET status='FAILED', failure_reason=%s, error_message=%s, completed_at=%s, attempts=attempts+1
            WHERE id=%s
            """,
            (reason, error_message, datetime.now(), queue_id),
        )

    def list_indicator_queue(
        self,
        dataset_id: int | None = None,
        statuses: Iterable[str] = ("PENDING",),
    ) -> list[IndicatorQueueItem]:
        status_list = tuple(statuses)
        placeholders = ",".join(["%s"] * len(status_list))
        params: list = list(status_list)
        where = [f"status IN ({placeholders})"]
        if dataset_id is not None:
            where.append("dataset_id=%s")
            params.append(dataset_id)
        rows = self.db.fetchall(
            f"SELECT * FROM dq_indicator_recalc_queue WHERE {' AND '.join(where)} ORDER BY id",
            tuple(params),
        )
        return [
            IndicatorQueueItem(
                id=row["id"],
                run_id=row["run_id"],
                dataset_id=row["dataset_id"],
                affected_start=row["affected_start"],
                affected_end=row["affected_end"],
                status=row["status"],
                attempts=row["attempts"],
                error_message=row.get("error_message"),
            )
            for row in rows
        ]

    def failure_reason_summary(self, run_id: str, limit: int = 10) -> list[dict]:
        return self.db.fetchall(
            """
            SELECT COALESCE(failure_reason, 'UNCLASSIFIED') AS failure_reason,
                   COUNT(*) AS count,
                   COALESCE(SUM(affected_rows), 0) AS affected_rows
            FROM dq_check_results
            WHERE run_id=%s AND status <> 'SUCCESS'
            GROUP BY COALESCE(failure_reason, 'UNCLASSIFIED')
            ORDER BY affected_rows DESC, count DESC
            LIMIT %s
            """,
            (run_id, int(limit)),
        )

    def dataset_issue_summary(self, run_id: str, limit: int = 10) -> list[dict]:
        return self.db.fetchall(
            """
            SELECT d.source, d.symbol, d.`interval`, r.check_type, r.status,
                   COALESCE(r.failure_reason, 'UNCLASSIFIED') AS failure_reason,
                   COUNT(*) AS count,
                   COALESCE(SUM(r.affected_rows), 0) AS affected_rows
            FROM dq_check_results r
            JOIN dq_dataset_registry d ON r.dataset_id=d.id
            WHERE r.run_id=%s AND r.status <> 'SUCCESS'
            GROUP BY d.source, d.symbol, d.`interval`, r.check_type, r.status,
                     COALESCE(r.failure_reason, 'UNCLASSIFIED')
            ORDER BY affected_rows DESC, count DESC
            LIMIT %s
            """,
            (run_id, int(limit)),
        )

    def failure_samples(self, run_id: str, limit: int = 5) -> list[dict]:
        return self.db.fetchall(
            """
            SELECT d.source, d.symbol, d.`interval`, r.check_type, r.status,
                   r.failure_reason, r.range_start, r.range_end, r.affected_rows,
                   r.details_json
            FROM dq_check_results r
            JOIN dq_dataset_registry d ON r.dataset_id=d.id
            WHERE r.run_id=%s AND r.status <> 'SUCCESS'
            ORDER BY r.affected_rows DESC, r.id ASC
            LIMIT %s
            """,
            (run_id, int(limit)),
        )

    def indicator_queue_summary(self, run_id: str, limit: int = 10) -> list[dict]:
        return self.db.fetchall(
            """
            SELECT d.source, d.symbol, d.`interval`, q.status,
                   COALESCE(q.failure_reason, 'UNCLASSIFIED') AS failure_reason,
                   COUNT(*) AS count
            FROM dq_indicator_recalc_queue q
            JOIN dq_dataset_registry d ON q.dataset_id=d.id
            WHERE q.run_id=%s
            GROUP BY d.source, d.symbol, d.`interval`, q.status,
                     COALESCE(q.failure_reason, 'UNCLASSIFIED')
            ORDER BY count DESC
            LIMIT %s
            """,
            (run_id, int(limit)),
        )

    def finish_run(self, run_id: str, finished_at: datetime, status: str, stats: RunStats) -> None:
        self.db.execute(
            """
            UPDATE dq_scan_runs
            SET finished_at=%s,status=%s,datasets_checked=%s,checks_passed=%s,
                checks_failed=%s,gaps_detected=%s,rows_repaired=%s,
                indicator_ranges_queued=%s,indicator_ranges_completed=%s,
                indicator_ranges_failed=%s,indicators_recalculated=%s,
                unresolved_errors=%s
            WHERE run_id=%s
            """,
            (
                finished_at,
                status,
                stats.datasets_checked,
                stats.checks_passed,
                stats.checks_failed,
                stats.gaps_detected,
                stats.rows_repaired,
                stats.indicator_ranges_queued,
                stats.indicator_ranges_completed,
                stats.indicator_ranges_failed,
                stats.indicators_recalculated,
                stats.unresolved_errors,
                run_id,
            ),
        )

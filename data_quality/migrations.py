from __future__ import annotations

from .db import Database


DDL = [
    """
    CREATE TABLE IF NOT EXISTS dq_dataset_registry (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        source VARCHAR(32) NOT NULL,
        symbol VARCHAR(32) NOT NULL,
        `interval` VARCHAR(8) NOT NULL,
        candle_table VARCHAR(128) NOT NULL,
        indicator_table VARCHAR(128) NOT NULL,
        actual_first_timestamp DATETIME NULL,
        actual_last_timestamp DATETIME NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uq_dq_dataset (source, symbol, `interval`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS dq_scan_runs (
        run_id VARCHAR(64) NOT NULL,
        mode VARCHAR(32) NOT NULL,
        started_at DATETIME NOT NULL,
        finished_at DATETIME NULL,
        status VARCHAR(32) NOT NULL,
        datasets_checked INT NOT NULL DEFAULT 0,
        checks_passed INT NOT NULL DEFAULT 0,
        checks_failed INT NOT NULL DEFAULT 0,
        gaps_detected BIGINT NOT NULL DEFAULT 0,
        rows_repaired BIGINT NOT NULL DEFAULT 0,
        indicator_ranges_queued BIGINT NOT NULL DEFAULT 0,
        indicator_ranges_completed BIGINT NOT NULL DEFAULT 0,
        indicator_ranges_failed BIGINT NOT NULL DEFAULT 0,
        indicators_recalculated BIGINT NOT NULL DEFAULT 0,
        unresolved_errors BIGINT NOT NULL DEFAULT 0,
        error_message TEXT NULL,
        PRIMARY KEY (run_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS dq_check_results (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        run_id VARCHAR(64) NOT NULL,
        dataset_id BIGINT UNSIGNED NOT NULL,
        check_type VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL,
        failure_reason VARCHAR(64) NULL,
        range_start DATETIME NULL,
        range_end DATETIME NULL,
        expected_value BIGINT NULL,
        actual_value BIGINT NULL,
        affected_rows BIGINT NOT NULL DEFAULT 0,
        details_json LONGTEXT NOT NULL,
        checked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        KEY idx_dq_check_run (run_id),
        KEY idx_dq_check_dataset (dataset_id),
        KEY idx_dq_check_reason (failure_reason, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS dq_indicator_recalc_queue (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        run_id VARCHAR(64) NOT NULL,
        dataset_id BIGINT UNSIGNED NOT NULL,
        affected_start DATETIME NOT NULL,
        affected_end DATETIME NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
        failure_reason VARCHAR(64) NULL,
        attempts INT NOT NULL DEFAULT 0,
        error_message TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        started_at DATETIME NULL,
        completed_at DATETIME NULL,
        PRIMARY KEY (id),
        KEY idx_dq_queue_work (status, dataset_id, affected_start),
        KEY idx_dq_queue_reason (failure_reason, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS dq_backfill_jobs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        run_id VARCHAR(64) NOT NULL,
        dataset_id BIGINT UNSIGNED NOT NULL,
        range_start DATETIME NOT NULL,
        range_end DATETIME NOT NULL,
        status VARCHAR(32) NOT NULL,
        failure_reason VARCHAR(64) NULL,
        error_message TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        KEY idx_dq_backfill_reason (failure_reason, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS dq_recalculation_jobs (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        run_id VARCHAR(64) NOT NULL,
        dataset_id BIGINT UNSIGNED NOT NULL,
        range_start DATETIME NOT NULL,
        range_end DATETIME NOT NULL,
        status VARCHAR(32) NOT NULL,
        failure_reason VARCHAR(64) NULL,
        error_message TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        KEY idx_dq_recalc_reason (failure_reason, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS dq_locks (
        lock_name VARCHAR(128) NOT NULL,
        owner VARCHAR(128) NOT NULL,
        acquired_at DATETIME NOT NULL,
        expires_at DATETIME NOT NULL,
        PRIMARY KEY (lock_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


ADDITIVE_COLUMNS = {
    "dq_check_results": {
        "failure_reason": "ALTER TABLE dq_check_results ADD COLUMN failure_reason VARCHAR(64) NULL AFTER status",
    },
    "dq_indicator_recalc_queue": {
        "failure_reason": "ALTER TABLE dq_indicator_recalc_queue ADD COLUMN failure_reason VARCHAR(64) NULL AFTER status",
    },
    "dq_backfill_jobs": {
        "failure_reason": "ALTER TABLE dq_backfill_jobs ADD COLUMN failure_reason VARCHAR(64) NULL AFTER status",
    },
    "dq_recalculation_jobs": {
        "failure_reason": "ALTER TABLE dq_recalculation_jobs ADD COLUMN failure_reason VARCHAR(64) NULL AFTER status",
    },
}


def _column_exists(db: Database, table: str, column: str) -> bool:
    row = db.fetchone(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s AND column_name=%s
        """,
        (__import__("os").getenv("DB_NAME"), table, column),
    )
    return bool(row and int(row["cnt"]) > 0)


def apply_migrations(db: Database) -> None:
    for statement in DDL:
        db.execute(statement)
    for table, columns in ADDITIVE_COLUMNS.items():
        for column, statement in columns.items():
            if db.table_exists(table) and not _column_exists(db, table, column):
                db.execute(statement)

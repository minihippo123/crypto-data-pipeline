from data_quality.db import Database
from data_quality.migrations import apply_migrations


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
        print("MariaDB production migration integration: SUCCESS")
    finally:
        db.close()


if __name__ == "__main__":
    main()

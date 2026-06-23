from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .indicators import recalculate_sma3, recalculate_sma3_range
from .models import AuditEvent, Gap
from .quality import INTERVAL_MINUTES, detect_duplicates, detect_gaps, detect_invalid
from .repository import SQLiteRepository
from .source import CandleSource


class DataQualityPipeline:
    def __init__(self, repository: SQLiteRepository, source: CandleSource | None = None) -> None:
        self.repository = repository
        self.source = source

    def run(self, symbol: str, interval: str, repair: bool = False) -> dict[str, object]:
        run_id = str(uuid4())
        candles = self.repository.list_candles(symbol, interval)
        gaps = detect_gaps(candles)
        duplicates = detect_duplicates(candles)
        invalid = detect_invalid(candles)

        self._audit(
            run_id,
            "scan",
            "SUCCESS",
            {
                "symbol": symbol,
                "interval": interval,
                "rows": len(candles),
                "rows_checked": len(candles),
                "gaps": len(gaps),
                "gap_ranges": len(gaps),
                "missing_candles": sum(gap.expected_count for gap in gaps),
                "duplicates": len(duplicates),
                "invalid": len(invalid),
                "invalid_rows": len(invalid),
            },
        )

        repair_summary = {
            "gaps_attempted": 0,
            "gaps_repaired": 0,
            "partial_gaps": 0,
            "unrecoverable_gaps": 0,
            "rows_written": 0,
            "indicator_ranges_queued": 0,
        }

        if repair and gaps:
            if self.source is None:
                raise ValueError("repair requested without a configured candle source")
            for gap in gaps:
                self._repair_gap(run_id, gap, repair_summary)
            self._audit(
                run_id,
                "repair",
                "SUCCESS" if repair_summary["gaps_repaired"] else "PARTIAL",
                {"rows_written": repair_summary["rows_written"]},
            )

        merge_summary = self._merge_pending_ranges(run_id, symbol, interval)
        indicator_summary = self._process_indicator_queue(run_id, symbol, interval)

        current = self.repository.list_candles(symbol, interval)
        if indicator_summary["indicators_recalculated"] == 0 and current:
            indicator_summary["indicators_recalculated"] = recalculate_sma3(
                self.repository, current
            )

        remaining_gaps = detect_gaps(current)
        remaining_invalid = detect_invalid(current)
        unresolved_queue = self.repository.count_queue(symbol, interval, "FAILED")

        status = (
            "SUCCESS"
            if not remaining_gaps and not remaining_invalid and unresolved_queue == 0
            else "PARTIAL"
        )
        result: dict[str, object] = {
            "status": status,
            "rows_checked": len(current),
            "gap_ranges_detected": len(gaps),
            "missing_candles_detected": sum(gap.expected_count for gap in gaps),
            "remaining_gap_ranges": len(remaining_gaps),
            "remaining_missing_candles": sum(gap.expected_count for gap in remaining_gaps),
            "invalid_rows": len(remaining_invalid),
            **repair_summary,
            **merge_summary,
            **indicator_summary,
            "unresolved_indicator_ranges": unresolved_queue,
            # Backward-compatible result keys used by the original public tests.
            "rows": len(current),
            "gaps_detected": len(gaps),
            "rows_repaired": repair_summary["rows_written"],
            "remaining_gaps": len(remaining_gaps),
        }
        self._audit(
            run_id,
            "revalidate",
            "SUCCESS" if not remaining_gaps else "ISSUES_REMAIN",
            {
                "remaining_gaps": len(remaining_gaps),
                "indicators_recalculated": indicator_summary["indicators_recalculated"],
            },
        )
        self._audit(run_id, "dataset_complete", status, result)
        return result

    def _repair_gap(self, run_id: str, gap: Gap, summary: dict[str, int]) -> None:
        summary["gaps_attempted"] += 1
        fetched = self.source.fetch_range(gap.symbol, gap.interval, gap.start, gap.end)
        accepted = [
            candle
            for candle in fetched
            if gap.start <= candle.timestamp <= gap.end and not candle.validate()
        ]
        out_of_range = len(fetched) - len(accepted)
        summary["rows_written"] += self.repository.upsert_candles(accepted)

        remaining = self._remaining_in_gap(gap)
        if remaining == 0:
            outcome = "SUCCESS"
            summary["gaps_repaired"] += 1
            self.repository.enqueue_indicator_range(
                gap.symbol, gap.interval, gap.start, gap.end
            )
            summary["indicator_ranges_queued"] += 1
        elif accepted:
            outcome = "PARTIAL"
            summary["partial_gaps"] += 1
        else:
            outcome = "UNRECOVERABLE"
            summary["unrecoverable_gaps"] += 1

        self._audit(
            run_id,
            "candle_repair",
            outcome,
            {
                "symbol": gap.symbol,
                "interval": gap.interval,
                "requested_start": gap.start,
                "requested_end": gap.end,
                "expected_rows": gap.expected_count,
                "received_rows": len(fetched),
                "accepted_rows": len(accepted),
                "out_of_range_rows": out_of_range,
                "remaining_missing": remaining,
                "indicator_queued": outcome == "SUCCESS",
            },
        )

    def _remaining_in_gap(self, gap: Gap) -> int:
        step = timedelta(minutes=INTERVAL_MINUTES[gap.interval])
        expected = {gap.start + step * index for index in range(gap.expected_count)}
        actual = {
            candle.timestamp
            for candle in self.repository.list_candles_range(
                gap.symbol, gap.interval, gap.start, gap.end
            )
        }
        return len(expected - actual)

    def _merge_pending_ranges(
        self, run_id: str, symbol: str, interval: str
    ) -> dict[str, int]:
        rows = self.repository.list_queue(symbol, interval, "PENDING")
        if not rows:
            return {"original_indicator_ranges": 0, "merged_indicator_ranges": 0}

        step = timedelta(minutes=INTERVAL_MINUTES[interval])
        groups: list[tuple[datetime, datetime, list[int]]] = []

        for row in rows:
            start = datetime.fromisoformat(row["affected_start"])
            end = datetime.fromisoformat(row["affected_end"])
            queue_id = int(row["id"])
            if groups and start <= groups[-1][1] + step:
                old_start, old_end, ids = groups[-1]
                groups[-1] = (old_start, max(old_end, end), ids + [queue_id])
            else:
                groups.append((start, end, [queue_id]))

        self.repository.supersede_queue_items([int(row["id"]) for row in rows])
        for start, end, _ in groups:
            self.repository.enqueue_indicator_range(symbol, interval, start, end)

        details = {
            "original_indicator_ranges": len(rows),
            "merged_indicator_ranges": len(groups),
        }
        self._audit(run_id, "indicator_queue_merge", "SUCCESS", details)
        return details

    def _process_indicator_queue(
        self, run_id: str, symbol: str, interval: str
    ) -> dict[str, int]:
        completed = 0
        failed = 0
        recalculated = 0
        inserted = 0
        updated = 0

        for row in self.repository.list_queue(symbol, interval, "PENDING"):
            queue_id = int(row["id"])
            start = datetime.fromisoformat(row["affected_start"])
            end = datetime.fromisoformat(row["affected_end"])
            self.repository.mark_queue_running(queue_id)
            try:
                result = recalculate_sma3_range(
                    self.repository, symbol, interval, start, end
                )
                self.repository.mark_queue_completed(queue_id)
                completed += 1
                recalculated += result.calculated_rows
                inserted += result.inserted_rows
                updated += result.updated_rows
                self._audit(
                    run_id,
                    "indicator_repair",
                    "SUCCESS",
                    {
                        "queue_id": queue_id,
                        "affected_start": start,
                        "affected_end": end,
                        "warmup_rows": result.warmup_rows,
                        "calculated_rows": result.calculated_rows,
                        "inserted_rows": result.inserted_rows,
                        "updated_rows": result.updated_rows,
                    },
                )
            except Exception as exc:
                self.repository.mark_queue_failed(queue_id, str(exc))
                failed += 1
                self._audit(
                    run_id,
                    "indicator_repair",
                    "FAILED",
                    {"queue_id": queue_id, "error": type(exc).__name__},
                )

        return {
            "indicator_ranges_completed": completed,
            "indicator_ranges_failed": failed,
            "indicators_recalculated": recalculated,
            "indicator_rows_inserted": inserted,
            "indicator_rows_updated": updated,
        }

    def _audit(self, run_id: str, stage: str, status: str, details: dict[str, object]) -> None:
        self.repository.write_audit_event(
            AuditEvent(
                run_id=run_id,
                stage=stage,
                status=status,
                occurred_at=datetime.now(timezone.utc),
                details=details,
            )
        )

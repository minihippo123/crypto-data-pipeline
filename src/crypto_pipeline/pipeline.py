from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .indicators import recalculate_sma3
from .models import AuditEvent
from .quality import detect_duplicates, detect_gaps, detect_invalid
from .repository import SQLiteRepository
from .source import CandleSource


class DataQualityPipeline:
    def __init__(self, repository: SQLiteRepository, source: CandleSource | None = None) -> None:
        self.repository = repository
        self.source = source

    def run(self, symbol: str, interval: str, repair: bool = False) -> dict[str, int]:
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
                "gaps": len(gaps),
                "duplicates": len(duplicates),
                "invalid": len(invalid),
            },
        )

        repaired = 0
        if repair and gaps:
            if self.source is None:
                raise ValueError("repair requested without a configured candle source")
            for gap in gaps:
                fetched = self.source.fetch_range(
                    gap.symbol, gap.interval, gap.start, gap.end
                )
                repaired += self.repository.upsert_candles(fetched)
            self._audit(run_id, "repair", "SUCCESS", {"rows_written": repaired})

        current = self.repository.list_candles(symbol, interval)
        indicators = recalculate_sma3(self.repository, current)
        remaining_gaps = detect_gaps(current)
        self._audit(
            run_id,
            "revalidate",
            "SUCCESS" if not remaining_gaps else "ISSUES_REMAIN",
            {
                "remaining_gaps": len(remaining_gaps),
                "indicators_recalculated": indicators,
            },
        )
        return {
            "rows": len(current),
            "gaps_detected": len(gaps),
            "rows_repaired": repaired,
            "remaining_gaps": len(remaining_gaps),
            "indicators_recalculated": indicators,
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

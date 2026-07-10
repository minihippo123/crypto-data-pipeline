from __future__ import annotations

from datetime import datetime

from notifications.base import NotificationMessage
from notifications.telegram import TelegramProvider


class DataQualityNotifier:
    def __init__(self) -> None:
        self.provider = TelegramProvider()

    def send(self, title: str, body: str, severity: str = "INFO") -> None:
        if not self.provider.enabled:
            return
        self.provider.send(NotificationMessage(title=title, body=body, severity=severity))

    def started(self, run_id: str, mode: str, dataset_count: int, repair_enabled: bool) -> None:
        self.send(
            "[CryptoDB Data Quality][STARTED]",
            "\n".join(
                [
                    f"Run ID: {run_id}",
                    f"Mode: {mode.upper()}",
                    f"Datasets: {dataset_count}",
                    f"Repair: {'ON' if repair_enabled else 'OFF'}",
                    f"Started at: {datetime.now().isoformat(timespec='seconds')}",
                ]
            ),
        )

    def progress(self, run_id: str, stats, current_dataset: str) -> None:
        self.send(
            "[CryptoDB Data Quality][PROGRESS]",
            "\n".join(
                [
                    f"Run ID: {run_id}",
                    f"Current: {current_dataset}",
                    f"Datasets checked: {stats.datasets_checked}",
                    f"Checks passed: {stats.checks_passed}",
                    f"Checks failed: {stats.checks_failed}",
                    f"Gaps detected: {stats.gaps_detected}",
                    f"Rows repaired: {stats.rows_repaired}",
                    f"Indicator queued: {stats.indicator_ranges_queued}",
                    f"Unresolved errors: {stats.unresolved_errors}",
                ]
            ),
        )

    def dataset_completed(self, run_id: str, dataset: str, status: str, summary: dict) -> None:
        body = [f"Run ID: {run_id}", f"Dataset: {dataset}", f"Status: {status}"]
        for key, value in summary.items():
            body.append(f"{key}: {value}")
        self.send("[CryptoDB Data Quality][DATASET]", "\n".join(body), "WARNING" if status != "SUCCESS" else "INFO")

    def critical(self, run_id: str, title: str, summary: dict) -> None:
        body = [f"Run ID: {run_id}", title]
        for key, value in summary.items():
            body.append(f"{key}: {value}")
        self.send("[CryptoDB Data Quality][CRITICAL]", "\n".join(body), "CRITICAL")

    def final(self, run_id: str, status: str, stats, reason_summary: list[dict], dataset_summary: list[dict], samples: list[dict], queue_summary: list[dict]) -> None:
        lines = [
            f"상태: {status}",
            f"Run ID: {run_id}",
            f"Dataset: {stats.datasets_checked}개",
            f"Checks failed: {stats.checks_failed}건",
            f"Candle gap ranges: {stats.gaps_detected}건",
            f"자동 복구 rows: {stats.rows_repaired}건",
            f"Indicator queue queued: {stats.indicator_ranges_queued}건",
            f"Indicator queue completed: {stats.indicator_ranges_completed}건",
            f"Indicator queue failed: {stats.indicator_ranges_failed}건",
            f"Indicator 재계산: {stats.indicators_recalculated}건",
            f"미해결 오류: {stats.unresolved_errors}건",
            "",
            "원인별 요약:",
        ]
        if reason_summary:
            for row in reason_summary[:10]:
                lines.append(f"- {row['failure_reason']}: {row['count']}건 / affected={row['affected_rows']}")
        else:
            lines.append("- 없음")
        lines.extend(["", "Top affected datasets:"])
        if dataset_summary:
            for row in dataset_summary[:10]:
                lines.append(
                    f"- {row['source']} {row['symbol']} {row['interval']} / {row['check_type']} / {row['failure_reason']} / affected={row['affected_rows']}"
                )
        else:
            lines.append("- 없음")
        lines.extend(["", "대표 실패 구간:"])
        if samples:
            for row in samples[:5]:
                lines.append(
                    f"- {row['source']} {row['symbol']} {row['interval']} {row['range_start']}~{row['range_end']} / {row['failure_reason']} / affected={row['affected_rows']}"
                )
        else:
            lines.append("- 없음")
        lines.extend(["", "Indicator queue 요약:"])
        if queue_summary:
            for row in queue_summary[:10]:
                lines.append(
                    f"- {row['source']} {row['symbol']} {row['interval']} / {row['status']} / {row['failure_reason']}: {row['count']}건"
                )
        else:
            lines.append("- 없음")
        lines.extend(
            [
                "",
                "다음 조치:",
                "- SOURCE_NO_DATA는 상장 전/거래소 원천 부재 가능성 확인",
                "- API_TIMEOUT/RATE_LIMIT은 request delay와 chunk size 조정",
                "- REVALIDATION_STILL_MISSING은 timestamp/interval 저장·조회 기준 점검",
                "- MISSING_WARMUP_CANDLES는 indicator warmup 범위와 원천 candle 확인",
                "- DB_* 오류는 테이블/컬럼/권한/lock 확인",
            ]
        )
        self.send("[CryptoDB Data Quality][FINAL]", "\n".join(lines), "CRITICAL" if status != "SUCCESS" else "INFO")

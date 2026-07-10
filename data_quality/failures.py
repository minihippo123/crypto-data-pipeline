from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FailureReason(StrEnum):
    SOURCE_NO_DATA = "SOURCE_NO_DATA"
    SOURCE_SYMBOL_NOT_LISTED = "SOURCE_SYMBOL_NOT_LISTED"
    SOURCE_INTERVAL_NOT_SUPPORTED = "SOURCE_INTERVAL_NOT_SUPPORTED"
    API_TIMEOUT = "API_TIMEOUT"
    API_RATE_LIMIT = "API_RATE_LIMIT"
    API_HTTP_ERROR = "API_HTTP_ERROR"
    API_EMPTY_RESPONSE = "API_EMPTY_RESPONSE"
    API_PARTIAL_RESPONSE = "API_PARTIAL_RESPONSE"
    API_PARSE_ERROR = "API_PARSE_ERROR"
    TIMESTAMP_MISMATCH = "TIMESTAMP_MISMATCH"
    DB_TABLE_MISSING = "DB_TABLE_MISSING"
    DB_INSERT_FAILED = "DB_INSERT_FAILED"
    DB_DUPLICATE_CONFLICT = "DB_DUPLICATE_CONFLICT"
    LOCAL_CANDLE_GAP = "LOCAL_CANDLE_GAP"
    LOCAL_INVALID_CANDLE = "LOCAL_INVALID_CANDLE"
    REVALIDATION_STILL_MISSING = "REVALIDATION_STILL_MISSING"
    MISSING_CANDLE_INPUT = "MISSING_CANDLE_INPUT"
    MISSING_WARMUP_CANDLES = "MISSING_WARMUP_CANDLES"
    INDICATOR_TABLE_MISSING = "INDICATOR_TABLE_MISSING"
    INDICATOR_SCHEMA_MISMATCH = "INDICATOR_SCHEMA_MISMATCH"
    INDICATOR_CALCULATION_ERROR = "INDICATOR_CALCULATION_ERROR"
    INDICATOR_DB_WRITE_FAILED = "INDICATOR_DB_WRITE_FAILED"
    QUEUE_STALE_RUNNING = "QUEUE_STALE_RUNNING"
    QUEUE_MAX_ATTEMPTS_EXCEEDED = "QUEUE_MAX_ATTEMPTS_EXCEEDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ClassifiedFailure:
    reason: FailureReason
    message: str
    retryable: bool
    operator_action: str


def classify_exception(exc: BaseException) -> ClassifiedFailure:
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return ClassifiedFailure(
            FailureReason.API_TIMEOUT,
            str(exc),
            True,
            "API timeout입니다. request delay를 늘리거나 작은 range로 재시도하세요.",
        )
    if "429" in text or "rate" in text:
        return ClassifiedFailure(
            FailureReason.API_RATE_LIMIT,
            str(exc),
            True,
            "거래소 rate limit 가능성이 큽니다. 호출 간격과 batch 크기를 낮추세요.",
        )
    if "http" in text or "status" in text or "500" in text or "502" in text or "503" in text:
        return ClassifiedFailure(
            FailureReason.API_HTTP_ERROR,
            str(exc),
            True,
            "거래소 HTTP 오류입니다. 동일 구간 재시도와 거래소 상태 확인이 필요합니다.",
        )
    if "json" in text or "parse" in text or "decode" in text:
        return ClassifiedFailure(
            FailureReason.API_PARSE_ERROR,
            str(exc),
            True,
            "API 응답 파싱 오류입니다. raw response 샘플을 확인하세요.",
        )
    if "duplicate" in text:
        return ClassifiedFailure(
            FailureReason.DB_DUPLICATE_CONFLICT,
            str(exc),
            False,
            "DB unique key/중복 충돌입니다. upsert 조건과 timestamp 기준을 확인하세요.",
        )
    if "table" in text and ("doesn't exist" in text or "not exist" in text or "unknown" in text):
        return ClassifiedFailure(
            FailureReason.DB_TABLE_MISSING,
            str(exc),
            False,
            "DB 테이블이 없습니다. migration 또는 수집 테이블 생성 여부를 확인하세요.",
        )
    if "mysql" in text or "mariadb" in text or "sql" in text or "pymysql" in text:
        return ClassifiedFailure(
            FailureReason.DB_INSERT_FAILED,
            str(exc),
            True,
            "DB write/query 오류입니다. SQL, 권한, lock, column schema를 확인하세요.",
        )
    return ClassifiedFailure(
        FailureReason.UNKNOWN,
        str(exc),
        True,
        "미분류 오류입니다. details_json 샘플을 확인해 reason rule을 추가하세요.",
    )


def classify_backfill_result(expected_count: int, returned_count: int, inserted_count: int) -> FailureReason | None:
    if expected_count <= 0:
        return None
    if returned_count == 0:
        return FailureReason.SOURCE_NO_DATA
    if returned_count < expected_count:
        return FailureReason.API_PARTIAL_RESPONSE
    if inserted_count < returned_count:
        return FailureReason.DB_INSERT_FAILED
    return None


def classify_revalidation(expected_missing: int, remaining_missing: int) -> FailureReason | None:
    if remaining_missing <= 0:
        return None
    if remaining_missing == expected_missing:
        return FailureReason.REVALIDATION_STILL_MISSING
    return FailureReason.API_PARTIAL_RESPONSE


def classify_indicator_failure(error_message: str | None, warmup_rows: int = 0, required_warmup: int = 0) -> FailureReason:
    if required_warmup and warmup_rows < required_warmup:
        return FailureReason.MISSING_WARMUP_CANDLES
    if not error_message:
        return FailureReason.UNKNOWN
    text = error_message.lower()
    if "table" in text and ("not" in text or "unknown" in text):
        return FailureReason.INDICATOR_TABLE_MISSING
    if "column" in text or "schema" in text:
        return FailureReason.INDICATOR_SCHEMA_MISMATCH
    if "nan" in text or "inf" in text or "calculation" in text:
        return FailureReason.INDICATOR_CALCULATION_ERROR
    if "mysql" in text or "sql" in text or "pymysql" in text:
        return FailureReason.INDICATOR_DB_WRITE_FAILED
    if "attempt" in text or "max" in text:
        return FailureReason.QUEUE_MAX_ATTEMPTS_EXCEEDED
    return FailureReason.UNKNOWN

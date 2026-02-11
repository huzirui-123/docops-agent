"""Threshold evaluator for CI smoke stability checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Thresholds:
    """Gate thresholds for CI smoke checks."""

    allow_429: bool = False
    max_tmp_delta_bytes: int = 5 * 1024 * 1024
    max_tmp_delta_count: int = 50
    max_total_ms_p95: int = 15_000
    max_queue_wait_ms_p95: int = 3_000
    require_no_leaks: bool = True
    require_internal_error_zero: bool = True
    require_non_200_zero: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate(
    load_summary: dict[str, Any],
    log_summary: dict[str, Any],
    th: Thresholds,
) -> list[str]:
    """Return stable failure keys; empty list means pass."""

    failures: list[str] = []

    leaked_pids = load_summary.get("leaked_pids")
    if th.require_no_leaks and isinstance(leaked_pids, list) and leaked_pids:
        failures.append("leaked_pids")

    outcome_counts = log_summary.get("outcome_counts")
    internal_error_count = 0
    if isinstance(outcome_counts, dict):
        internal_error_count = _as_int(outcome_counts.get("internal_error")) or 0
    if th.require_internal_error_zero and internal_error_count > 0:
        failures.append("internal_error")

    tmp_delta_bytes = _metric_int(
        load_summary,
        "worst_tmp_delta_bytes",
        "tmp_delta_bytes",
    )
    if tmp_delta_bytes is not None and tmp_delta_bytes > th.max_tmp_delta_bytes:
        failures.append("tmp_delta_bytes")

    tmp_delta_count = _metric_int(
        load_summary,
        "worst_tmp_delta_count",
        "tmp_delta_count",
    )
    if tmp_delta_count is not None and tmp_delta_count > th.max_tmp_delta_count:
        failures.append("tmp_delta_count")

    total_ms_p95 = _first_int(
        load_summary.get("worst_total_ms_p95"),
        load_summary.get("total_ms_p95"),
        log_summary.get("total_ms_p95"),
    )
    if total_ms_p95 is not None and total_ms_p95 > th.max_total_ms_p95:
        failures.append("total_ms_p95")

    queue_wait_p95 = _first_int(
        load_summary.get("worst_queue_wait_ms_p95"),
        load_summary.get("queue_wait_ms_p95"),
        log_summary.get("queue_wait_ms_p95"),
    )
    if queue_wait_p95 is not None and queue_wait_p95 > th.max_queue_wait_ms_p95:
        failures.append("queue_wait_ms_p95")

    status_counts = _status_counts(load_summary, log_summary)
    status_429 = status_counts.get("429", 0)
    if not th.allow_429 and status_429 > 0:
        failures.append("http_429")

    if th.require_non_200_zero:
        non_200 = 0
        for code, count in status_counts.items():
            if code == "200":
                continue
            if code == "429" and th.allow_429:
                continue
            non_200 += count
        if non_200 > 0:
            failures.append("http_non_200")

    return sorted(set(failures))


def _metric_int(summary: dict[str, Any], worst_key: str, normal_key: str) -> int | None:
    return _first_int(summary.get(worst_key), summary.get(normal_key))


def _status_counts(load_summary: dict[str, Any], log_summary: dict[str, Any]) -> dict[str, int]:
    """Prefer load test status counts, fallback to log summary counts."""

    status_counts = load_summary.get("status_counts")
    if isinstance(status_counts, dict):
        return {str(key): _as_int(value) or 0 for key, value in status_counts.items()}

    log_status = log_summary.get("http_status_counts")
    if isinstance(log_status, dict):
        return {str(key): _as_int(value) or 0 for key, value in log_status.items()}

    return {}


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _as_int(value)
        if parsed is not None:
            return parsed
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None

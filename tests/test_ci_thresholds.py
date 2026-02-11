from __future__ import annotations

from scripts.ci_thresholds import Thresholds, evaluate


def test_evaluate_fails_on_leaked_pids() -> None:
    load_summary = {"leaked_pids": [12345], "status_counts": {"200": 1}}
    log_summary = {"outcome_counts": {"ok": 1}, "http_status_counts": {"200": 1}}
    failures = evaluate(load_summary, log_summary, Thresholds())
    assert "leaked_pids" in failures


def test_evaluate_fails_on_internal_error() -> None:
    load_summary = {"leaked_pids": [], "status_counts": {"200": 1}}
    log_summary = {
        "outcome_counts": {"ok": 1, "internal_error": 2},
        "http_status_counts": {"200": 1, "500": 2},
    }
    failures = evaluate(load_summary, log_summary, Thresholds())
    assert "internal_error" in failures


def test_evaluate_fails_on_tmp_delta_bytes() -> None:
    load_summary = {
        "leaked_pids": [],
        "status_counts": {"200": 1},
        "tmp_delta_bytes": 20,
        "tmp_delta_count": 1,
    }
    log_summary = {"outcome_counts": {"ok": 1}, "http_status_counts": {"200": 1}}
    thresholds = Thresholds(max_tmp_delta_bytes=10)
    failures = evaluate(load_summary, log_summary, thresholds)
    assert "tmp_delta_bytes" in failures


def test_evaluate_fails_on_p95_thresholds() -> None:
    load_summary = {"leaked_pids": [], "status_counts": {"200": 1}}
    log_summary = {
        "outcome_counts": {"ok": 1},
        "http_status_counts": {"200": 1},
        "total_ms_p95": 2000,
        "queue_wait_ms_p95": 500,
    }
    thresholds = Thresholds(max_total_ms_p95=1000, max_queue_wait_ms_p95=300)
    failures = evaluate(load_summary, log_summary, thresholds)
    assert "total_ms_p95" in failures
    assert "queue_wait_ms_p95" in failures


def test_evaluate_fails_on_429_when_not_allowed() -> None:
    load_summary = {"leaked_pids": [], "status_counts": {"200": 1, "429": 2}}
    log_summary = {"outcome_counts": {"ok": 1}, "http_status_counts": {"200": 1, "429": 2}}
    failures = evaluate(load_summary, log_summary, Thresholds(allow_429=False))
    assert "http_429" in failures


def test_evaluate_prefers_worst_case_fields_when_present() -> None:
    load_summary = {
        "leaked_pids": [],
        "status_counts": {"200": 2},
        "worst_tmp_delta_bytes": 80,
        "tmp_delta_bytes": 10,
        "worst_tmp_delta_count": 7,
        "tmp_delta_count": 1,
        "worst_total_ms_p95": 2500,
        "total_ms_p95": 800,
        "worst_queue_wait_ms_p95": 500,
        "queue_wait_ms_p95": 100,
    }
    log_summary = {"outcome_counts": {"ok": 2}, "http_status_counts": {"200": 2}}
    thresholds = Thresholds(
        max_tmp_delta_bytes=50,
        max_tmp_delta_count=5,
        max_total_ms_p95=2000,
        max_queue_wait_ms_p95=300,
    )
    failures = evaluate(load_summary, log_summary, thresholds)
    assert "tmp_delta_bytes" in failures
    assert "tmp_delta_count" in failures
    assert "total_ms_p95" in failures
    assert "queue_wait_ms_p95" in failures

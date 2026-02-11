from __future__ import annotations

from scripts.ci_thresholds import Thresholds, evaluate


def test_evaluate_fails_on_leaked_pids() -> None:
    load_summary = {"leaked_pids": [12345], "status_counts": {"200": 1}}
    log_summary = {"outcome_counts": {"ok": 1}, "http_status_counts": {"200": 1}}
    failures = evaluate(load_summary, log_summary, Thresholds())
    assert any("leaked_pids" in item for item in failures)


def test_evaluate_fails_on_internal_error() -> None:
    load_summary = {"leaked_pids": [], "status_counts": {"200": 1}}
    log_summary = {
        "outcome_counts": {"ok": 1, "internal_error": 2},
        "http_status_counts": {"200": 1, "500": 2},
    }
    failures = evaluate(load_summary, log_summary, Thresholds())
    assert any("internal_error" in item for item in failures)


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
    assert any("tmp_delta_bytes" in item for item in failures)


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
    assert any("total_ms_p95" in item for item in failures)
    assert any("queue_wait_ms_p95" in item for item in failures)


def test_evaluate_fails_on_429_when_not_allowed() -> None:
    load_summary = {"leaked_pids": [], "status_counts": {"200": 1, "429": 2}}
    log_summary = {"outcome_counts": {"ok": 1}, "http_status_counts": {"200": 1, "429": 2}}
    failures = evaluate(load_summary, log_summary, Thresholds(allow_429=False))
    assert any("http_429" in item for item in failures)

from __future__ import annotations

import json
import socket as socket_mod
from pathlib import Path

from scripts.ci_smoke import (
    _merge_repeat_summaries,
    _pick_free_port,
    _prefix_failures,
    _render_ci_markdown,
    _write_ci_result_artifacts,
)


def test_pick_free_port_returns_valid_port(monkeypatch) -> None:
    class _FakeSocket:
        def __enter__(self) -> _FakeSocket:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def bind(self, addr: tuple[str, int]) -> None:
            _ = addr

        def getsockname(self) -> tuple[str, int]:
            return ("127.0.0.1", 43210)

    def _fake_socket(family: int, socktype: int) -> _FakeSocket:
        assert family == socket_mod.AF_INET
        assert socktype == socket_mod.SOCK_STREAM
        return _FakeSocket()

    monkeypatch.setattr("scripts.ci_smoke.socket.socket", _fake_socket)
    port = _pick_free_port("127.0.0.1")
    assert isinstance(port, int)
    assert port == 43210


def test_merge_repeat_summaries_ignores_warmup_and_uses_worst_case() -> None:
    rounds = [
        {
            "round": 1,
            "phase": "warmup",
            "summary": {
                "status_counts": {"200": 1},
                "leaked_pids": [999],
                "tmp_delta_count": 100,
                "tmp_delta_bytes": 1000,
                "latency_ms": {"p95": 5000},
            },
        },
        {
            "round": 2,
            "phase": "measurement",
            "summary": {
                "status_counts": {"200": 2, "429": 1},
                "leaked_pids": [123],
                "timeout_request_ids": ["a"],
                "tmp_delta_count": 3,
                "tmp_delta_bytes": 30,
                "latency_ms": {"p95": 300},
            },
        },
        {
            "round": 3,
            "phase": "measurement",
            "summary": {
                "status_counts": {"200": 1},
                "leaked_pids": [456, 123],
                "timeout_request_ids": ["b"],
                "tmp_delta_count": 5,
                "tmp_delta_bytes": 10,
                "latency_ms": {"p95": 100},
            },
        },
    ]

    merged = _merge_repeat_summaries(rounds)

    assert merged["measurement_rounds"] == 2
    assert merged["warmup_rounds"] == 1
    assert merged["status_counts"] == {"200": 3, "429": 1}
    assert merged["leaked_pids"] == [123, 456]
    assert merged["tmp_delta_count"] == 5
    assert merged["tmp_delta_bytes"] == 30
    assert merged["worst_latency_ms_p95"] == 300
    assert merged["timeout_request_ids"] == ["a", "b"]


def test_prefix_failures() -> None:
    assert _prefix_failures("tooling_failure", ["x", "y"]) == [
        "tooling_failure:x",
        "tooling_failure:y",
    ]


def test_render_ci_markdown_contains_required_sections() -> None:
    result = {
        "ok": False,
        "duration_ms": 1234,
        "picked_port": 8001,
        "repeat": 3,
        "repeat_warmup": 1,
        "tooling_failures": ["tooling_failure:healthcheck_failed"],
        "stability_failures": ["stability_failure:tmp_delta_bytes"],
        "load_summary": {
            "leaked_pids": [123],
            "worst_tmp_delta_count": 8,
            "worst_tmp_delta_bytes": 64,
            "status_counts": {"200": 2, "429": 1},
        },
        "log_summary": {"total_ms_p95": 2500, "queue_wait_ms_p95": 120},
        "paths": {
            "server_log": "artifacts/server.log",
            "load_summary": "artifacts/load_summary.json",
            "log_summary": "artifacts/log_summary.json",
            "ci_result": "artifacts/ci_result.json",
            "ci_result_md": "artifacts/ci_result.md",
        },
        "rounds": [{"summary_path": "artifacts/load_summary.1.json"}],
        "server_log_excerpt": ["line1", "line2"],
    }
    markdown = _render_ci_markdown(result)
    assert "Overall:" in markdown
    assert "## Tooling Failures" in markdown
    assert "## Stability Failures" in markdown
    assert "## Artifacts" in markdown
    assert "## Reproduce" in markdown
    assert "## server.log excerpt" in markdown
    assert "line1" in markdown


def test_write_ci_result_artifacts_writes_markdown_on_failure_even_if_disabled(
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "ci_result.json"
    md_path = tmp_path / "ci_result.md"
    result = {
        "ok": False,
        "failures": ["tooling_failure:x"],
        "tooling_failures": ["tooling_failure:x"],
        "stability_failures": [],
        "load_summary": {},
        "log_summary": {},
        "paths": {"ci_result": str(json_path), "ci_result_md": str(md_path)},
        "server_log_excerpt": [],
    }

    _write_ci_result_artifacts(
        result=result,
        ci_result_path=json_path,
        ci_result_md_path=md_path,
        write_md=False,
    )

    assert json_path.exists()
    assert md_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["failures"] == ["tooling_failure:x"]
    markdown = md_path.read_text(encoding="utf-8")
    assert "Tooling Failures" in markdown

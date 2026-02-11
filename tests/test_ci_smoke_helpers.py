from __future__ import annotations

import socket as socket_mod

from scripts.ci_smoke import _merge_repeat_summaries, _pick_free_port, _prefix_failures


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

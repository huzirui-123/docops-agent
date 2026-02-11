#!/usr/bin/env python3
"""Run CI smoke stability checks for docops API."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, TextIO

import httpx

from scripts.ci_thresholds import Thresholds, evaluate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CI smoke checks against local docops API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--port-retries", type=int, default=5)
    parser.add_argument("--skill", default="meeting_notice")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--repeat-warmup", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0, help="load_test request timeout")
    parser.add_argument("--health-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--health-interval-seconds", type=float, default=0.3)
    parser.add_argument("--leak-grace-ms", type=int, default=1500)
    parser.add_argument(
        "--tmp-root",
        default=tempfile.gettempdir(),
        help="tmp root path used by load_test watermark stats",
    )
    parser.add_argument("--artifacts-dir", default="artifacts")
    parser.add_argument("--fail-on-leaks", action="store_true", default=True)
    parser.add_argument("--no-fail-on-leaks", action="store_false", dest="fail_on_leaks")
    parser.add_argument(
        "--write-md",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write markdown report to artifacts/ci_result.md",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    artifacts_dir = Path(args.artifacts_dir).expanduser()
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    server_log_path = artifacts_dir / "server.log"
    load_summary_path = artifacts_dir / "load_summary.json"
    log_summary_path = artifacts_dir / "log_summary.json"
    ci_result_path = artifacts_dir / "ci_result.json"
    ci_result_md_path = artifacts_dir / "ci_result.md"

    result: dict[str, Any] = {
        "ok": False,
        "base_url": None,
        "picked_port": None,
        "repeat": max(1, args.repeat),
        "repeat_warmup": max(0, args.repeat_warmup),
        "paths": {
            "server_log": str(server_log_path),
            "load_summary": str(load_summary_path),
            "log_summary": str(log_summary_path),
            "ci_result": str(ci_result_path),
            "ci_result_md": str(ci_result_md_path),
        },
        "rounds": [],
        "port_retry_attempts": [],
        "thresholds": {},
        "tooling_failures": [],
        "stability_failures": [],
        "failures": [],
        "summarize_returncode": None,
    }

    started = time.perf_counter()
    server_process: subprocess.Popen[str] | None = None
    log_file = server_log_path.open("w", encoding="utf-8")

    try:
        server_process, picked_port, attempts = _start_server_with_retry(
            host=args.host,
            requested_port=args.port,
            port_retries=max(1, args.port_retries),
            concurrency=args.concurrency,
            cwd=repo_root,
            log_file=log_file,
            health_timeout_seconds=args.health_timeout_seconds,
            health_interval_seconds=args.health_interval_seconds,
        )
        result["picked_port"] = picked_port
        result["base_url"] = f"http://{args.host}:{picked_port}"
        result["port_retry_attempts"] = attempts

        total_rounds = max(1, args.repeat) + max(0, args.repeat_warmup)
        for round_index in range(1, total_rounds + 1):
            phase = "warmup" if round_index <= max(0, args.repeat_warmup) else "measurement"
            round_record = _run_load_round(
                repo_root=repo_root,
                artifacts_dir=artifacts_dir,
                base_url=result["base_url"],
                round_index=round_index,
                phase=phase,
                skill=args.skill,
                requests=args.requests,
                concurrency=args.concurrency,
                timeout=args.timeout,
                leak_grace_ms=args.leak_grace_ms,
                tmp_root=Path(args.tmp_root).expanduser(),
                fail_on_leaks=args.fail_on_leaks,
            )
            result["rounds"].append(round_record)
            returncode = round_record.get("returncode")
            has_summary = bool(round_record.get("summary"))
            if isinstance(returncode, int) and returncode != 0 and not has_summary:
                result["tooling_failures"].append(
                    f"tooling_failure:load_test_returncode:{round_index}:{returncode}"
                )

        merged_load_summary = _merge_repeat_summaries(result["rounds"])
        if not merged_load_summary.get("measurement_rounds"):
            result["tooling_failures"].append("tooling_failure:no_measurement_rounds")
        load_summary_path.write_text(
            json.dumps(merged_load_summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        _flush_log_file(log_file)

        summarize_cmd = [
            sys.executable,
            str(repo_root / "scripts" / "summarize_logs.py"),
            "--json",
            str(server_log_path),
        ]
        summarize_completed = subprocess.run(  # noqa: S603
            summarize_cmd,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        result["summarize_returncode"] = summarize_completed.returncode
        (artifacts_dir / "summarize.stdout.log").write_text(
            summarize_completed.stdout,
            encoding="utf-8",
        )
        (artifacts_dir / "summarize.stderr.log").write_text(
            summarize_completed.stderr,
            encoding="utf-8",
        )
        if summarize_completed.returncode == 0:
            log_summary_path.write_text(
                summarize_completed.stdout,
                encoding="utf-8",
            )
        else:
            result["tooling_failures"].append(
                f"tooling_failure:summarize_logs_returncode:{summarize_completed.returncode}"
            )

        log_summary = _read_json_file(log_summary_path)
        thresholds = _thresholds_from_env()
        result["thresholds"] = thresholds.to_dict()

        threshold_failures = evaluate(merged_load_summary, log_summary, thresholds)
        result["stability_failures"] = _prefix_failures("stability_failure", threshold_failures)

        result["load_summary"] = merged_load_summary
        result["log_summary"] = log_summary
    except Exception as exc:  # noqa: BLE001
        if not result["tooling_failures"] and not result["stability_failures"]:
            result["tooling_failures"].append(
                f"tooling_failure:ci_smoke_exception:{exc.__class__.__name__}"
            )
    finally:
        _terminate_process(server_process)
        log_file.close()

    result["failures"] = [
        *result["tooling_failures"],
        *result["stability_failures"],
    ]
    result["ok"] = not result["failures"]
    result["duration_ms"] = int((time.perf_counter() - started) * 1000)

    ci_result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if args.write_md:
        ci_result_md_path.write_text(_render_ci_markdown(result), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)


def _start_server_with_retry(
    *,
    host: str,
    requested_port: int,
    port_retries: int,
    concurrency: int,
    cwd: Path,
    log_file: TextIO,
    health_timeout_seconds: float,
    health_interval_seconds: float,
) -> tuple[subprocess.Popen[str], int, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []

    for attempt_index in range(1, port_retries + 1):
        candidate_port = requested_port
        if requested_port == 0:
            candidate_port = _pick_free_port(host)

        process = _start_server(
            host=host,
            port=candidate_port,
            concurrency=concurrency,
            cwd=cwd,
            log_file=log_file,
        )

        base_url = f"http://{host}:{candidate_port}"
        health_ok = _wait_for_health(
            base_url=base_url,
            timeout_seconds=health_timeout_seconds,
            interval_seconds=health_interval_seconds,
            process=process,
        )

        attempts.append(
            {
                "attempt": attempt_index,
                "port": candidate_port,
                "health_ok": health_ok,
                "process_exit_code": process.poll(),
            }
        )

        if health_ok:
            return process, candidate_port, attempts

        _terminate_process(process)

    raise RuntimeError("tooling_failure:start_server_retry_exhausted")


def _start_server(
    *,
    host: str,
    port: int,
    concurrency: int,
    cwd: Path,
    log_file: TextIO,
) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.setdefault("DOCOPS_ENABLE_WEB_CONSOLE", "0")
    env.setdefault("DOCOPS_ENABLE_META", "0")
    env.setdefault("PYTHONUNBUFFERED", "1")
    existing = _parse_int(env.get("DOCOPS_MAX_CONCURRENCY"), default=2)
    env["DOCOPS_MAX_CONCURRENCY"] = str(max(existing, concurrency))

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.api.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    return subprocess.Popen(  # noqa: S603
        cmd,
        cwd=cwd,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_health(
    *,
    base_url: str,
    timeout_seconds: float,
    interval_seconds: float,
    process: subprocess.Popen[str],
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            try:
                response = client.get(f"{base_url}/healthz")
                if response.status_code == 200:
                    payload = response.json()
                    if isinstance(payload, dict) and payload.get("status") == "ok":
                        return True
            except Exception:  # noqa: BLE001
                pass
            time.sleep(interval_seconds)
    return False


def _run_load_round(
    *,
    repo_root: Path,
    artifacts_dir: Path,
    base_url: str,
    round_index: int,
    phase: str,
    skill: str,
    requests: int,
    concurrency: int,
    timeout: float,
    leak_grace_ms: int,
    tmp_root: Path,
    fail_on_leaks: bool,
) -> dict[str, Any]:
    summary_path = artifacts_dir / f"load_summary.{round_index}.json"
    stdout_path = artifacts_dir / f"load_test.{round_index}.stdout.log"
    stderr_path = artifacts_dir / f"load_test.{round_index}.stderr.log"

    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "load_test.py"),
        "--base-url",
        base_url,
        "--skill",
        skill,
        "--requests",
        str(requests),
        "--concurrency",
        str(concurrency),
        "--timeout",
        str(timeout),
        "--check-subprocess-leaks",
        "--leak-grace-ms",
        str(leak_grace_ms),
        "--tmp-root",
        str(tmp_root),
        "--write-summary",
        str(summary_path),
    ]
    if fail_on_leaks:
        cmd.append("--fail-on-leaks")

    completed = subprocess.run(  # noqa: S603
        cmd,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    summary = _read_json_file(summary_path)
    if summary:
        summary["phase"] = phase
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    return {
        "round": round_index,
        "phase": phase,
        "summary_path": str(summary_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "returncode": completed.returncode,
        "summary": summary,
    }


def _merge_repeat_summaries(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    measurement_summaries = [
        record["summary"]
        for record in rounds
        if record.get("phase") == "measurement" and isinstance(record.get("summary"), dict)
    ]

    status_counts: dict[str, int] = {}
    leaked_pids: set[int] = set()
    timeout_ids: set[str] = set()
    tmp_delta_count_max = 0
    tmp_delta_bytes_max = 0
    latency_p95_max = 0

    for summary in measurement_summaries:
        raw_status = summary.get("status_counts")
        if isinstance(raw_status, dict):
            for key, value in raw_status.items():
                count = _parse_int(value, default=0)
                status_counts[str(key)] = status_counts.get(str(key), 0) + count

        raw_leaks = summary.get("leaked_pids")
        if isinstance(raw_leaks, list):
            for item in raw_leaks:
                if isinstance(item, int):
                    leaked_pids.add(item)

        raw_timeout_ids = summary.get("timeout_request_ids")
        if isinstance(raw_timeout_ids, list):
            for item in raw_timeout_ids:
                if isinstance(item, str) and item:
                    timeout_ids.add(item)

        tmp_delta_count = _parse_int(summary.get("tmp_delta_count"), default=0)
        tmp_delta_bytes = _parse_int(summary.get("tmp_delta_bytes"), default=0)
        tmp_delta_count_max = max(tmp_delta_count_max, tmp_delta_count)
        tmp_delta_bytes_max = max(tmp_delta_bytes_max, tmp_delta_bytes)

        latency = summary.get("latency_ms")
        if isinstance(latency, dict):
            p95 = _parse_int(latency.get("p95"), default=0)
            latency_p95_max = max(latency_p95_max, p95)

    return {
        "measurement_rounds": len(measurement_summaries),
        "warmup_rounds": len([item for item in rounds if item.get("phase") == "warmup"]),
        "status_counts": dict(sorted(status_counts.items())),
        "leaked_pids": sorted(leaked_pids),
        "timeout_request_ids": sorted(timeout_ids),
        "tmp_delta_count": tmp_delta_count_max,
        "tmp_delta_bytes": tmp_delta_bytes_max,
        "worst_tmp_delta_count": tmp_delta_count_max,
        "worst_tmp_delta_bytes": tmp_delta_bytes_max,
        "worst_latency_ms_p95": latency_p95_max,
    }


def _terminate_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return


def _thresholds_from_env() -> Thresholds:
    return Thresholds(
        allow_429=_parse_bool(os.getenv("DOCOPS_CI_ALLOW_429"), default=False),
        max_tmp_delta_bytes=_parse_int(
            os.getenv("DOCOPS_CI_MAX_TMP_DELTA_BYTES"),
            default=5 * 1024 * 1024,
        ),
        max_tmp_delta_count=_parse_int(
            os.getenv("DOCOPS_CI_MAX_TMP_DELTA_COUNT"),
            default=50,
        ),
        max_total_ms_p95=_parse_int(
            os.getenv("DOCOPS_CI_MAX_TOTAL_MS_P95"),
            default=15_000,
        ),
        max_queue_wait_ms_p95=_parse_int(
            os.getenv("DOCOPS_CI_MAX_QUEUE_WAIT_MS_P95"),
            default=3_000,
        ),
        require_no_leaks=_parse_bool(
            os.getenv("DOCOPS_CI_REQUIRE_NO_LEAKS"),
            default=True,
        ),
        require_internal_error_zero=_parse_bool(
            os.getenv("DOCOPS_CI_REQUIRE_INTERNAL_ERROR_ZERO"),
            default=True,
        ),
        require_non_200_zero=_parse_bool(
            os.getenv("DOCOPS_CI_REQUIRE_NON_200_ZERO"),
            default=True,
        ),
    )


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _prefix_failures(prefix: str, failures: list[str]) -> list[str]:
    return [f"{prefix}:{item}" for item in failures]


def _flush_log_file(log_file: TextIO) -> None:
    try:
        log_file.flush()
        os.fsync(log_file.fileno())
    except Exception:  # noqa: BLE001
        return


def _render_ci_markdown(result: dict[str, Any]) -> str:
    ok = bool(result.get("ok"))
    icon = "✅" if ok else "❌"

    tooling = result.get("tooling_failures", [])
    stability = result.get("stability_failures", [])
    load_summary = result.get("load_summary", {})
    log_summary = result.get("log_summary", {})
    picked_port = result.get("picked_port")

    lines = [
        "# CI Smoke Result",
        "",
        f"Overall: {icon} {'PASS' if ok else 'FAIL'}",
        f"Duration: {result.get('duration_ms', 0)} ms",
        f"Port: {picked_port}",
        f"Repeat: {result.get('repeat')} (warmup={result.get('repeat_warmup')})",
        "",
        "## Tooling Failures",
    ]

    if isinstance(tooling, list) and tooling:
        lines.extend([f"- {item}" for item in tooling])
    else:
        lines.append("- none")

    lines.append("")
    lines.append("## Stability Failures")
    if isinstance(stability, list) and stability:
        lines.extend([f"- {item}" for item in stability])
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Worst-case Metrics",
            f"- leaked_pids: {load_summary.get('leaked_pids', [])}",
            f"- tmp_delta_count(max): {load_summary.get('worst_tmp_delta_count')}",
            f"- tmp_delta_bytes(max): {load_summary.get('worst_tmp_delta_bytes')}",
            f"- total_ms_p95: {log_summary.get('total_ms_p95')}",
            f"- queue_wait_ms_p95: {log_summary.get('queue_wait_ms_p95')}",
            f"- status_counts: {load_summary.get('status_counts', {})}",
            "",
            "## Reproduce",
            (
                "poetry run python scripts/ci_smoke.py "
                f"--host 127.0.0.1 --port {picked_port or 0} --requests 20 "
                f"--concurrency 6 --skill meeting_notice --artifacts-dir artifacts"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _pick_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
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
            return default
    return default


if __name__ == "__main__":
    main()

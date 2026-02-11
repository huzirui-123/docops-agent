#!/usr/bin/env python3
"""Run CI smoke stability checks for docops API."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from scripts.ci_thresholds import Thresholds, evaluate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CI smoke checks against local docops API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--skill", default="meeting_notice")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=6)
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

    result: dict[str, Any] = {
        "ok": False,
        "base_url": f"http://{args.host}:{args.port}",
        "paths": {
            "server_log": str(server_log_path),
            "load_summary": str(load_summary_path),
            "log_summary": str(log_summary_path),
            "ci_result": str(ci_result_path),
        },
        "thresholds": {},
        "failures": [],
        "load_test_returncode": None,
        "summarize_returncode": None,
    }

    started = time.perf_counter()
    server_process: subprocess.Popen[str] | None = None
    log_file = server_log_path.open("w", encoding="utf-8")

    try:
        server_process = _start_server(
            host=args.host,
            port=args.port,
            concurrency=args.concurrency,
            cwd=repo_root,
            log_file=log_file,
        )

        health_ok = _wait_for_health(
            base_url=result["base_url"],
            timeout_seconds=args.health_timeout_seconds,
            interval_seconds=args.health_interval_seconds,
            process=server_process,
        )
        if not health_ok:
            result["failures"].append("healthcheck_failed")
            raise RuntimeError("healthcheck_failed")

        load_cmd = [
            sys.executable,
            str(repo_root / "scripts" / "load_test.py"),
            "--base-url",
            result["base_url"],
            "--skill",
            str(args.skill),
            "--requests",
            str(args.requests),
            "--concurrency",
            str(args.concurrency),
            "--timeout",
            str(args.timeout),
            "--check-subprocess-leaks",
            "--leak-grace-ms",
            str(args.leak_grace_ms),
            "--tmp-root",
            str(Path(args.tmp_root).expanduser()),
            "--write-summary",
            str(load_summary_path),
        ]
        if args.fail_on_leaks:
            load_cmd.append("--fail-on-leaks")

        load_completed = subprocess.run(  # noqa: S603
            load_cmd,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        result["load_test_returncode"] = load_completed.returncode
        (artifacts_dir / "load_test.stdout.log").write_text(
            load_completed.stdout,
            encoding="utf-8",
        )
        (artifacts_dir / "load_test.stderr.log").write_text(
            load_completed.stderr,
            encoding="utf-8",
        )
        if load_completed.returncode != 0 and not load_summary_path.exists():
            result["failures"].append(f"load_test_returncode:{load_completed.returncode}")

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
            result["failures"].append(
                f"summarize_logs_returncode:{summarize_completed.returncode}"
            )

        load_summary = _read_json_file(load_summary_path)
        log_summary = _read_json_file(log_summary_path)
        thresholds = _thresholds_from_env()
        result["thresholds"] = thresholds.to_dict()
        threshold_failures = evaluate(load_summary, log_summary, thresholds)
        result["failures"].extend(threshold_failures)
    except Exception as exc:  # noqa: BLE001
        if not result["failures"]:
            result["failures"].append(f"ci_smoke_exception:{exc.__class__.__name__}")
    finally:
        _terminate_process(server_process)
        log_file.close()

    result["ok"] = not result["failures"]
    result["duration_ms"] = int((time.perf_counter() - started) * 1000)
    ci_result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)


def _start_server(
    *,
    host: str,
    port: int,
    concurrency: int,
    cwd: Path,
    log_file: Any,
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


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


if __name__ == "__main__":
    main()

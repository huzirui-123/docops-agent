#!/usr/bin/env python3
"""Local load test utility for the FastAPI endpoint.

This script targets a real running service via base_url.
It does not use ASGITransport.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import os
import platform
import subprocess
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx
from docx import Document


@dataclass(frozen=True)
class RequestResult:
    status_code: int
    latency_ms: int
    request_id: str | None
    subprocess_pid: int | None


def _build_docx_bytes(skill: str) -> bytes:
    placeholders = {
        "meeting_notice": "【MEETING_TITLE】",
        "training_notice": "【TRAINING_TITLE】",
        "inspection_record": "【INSPECTION_SUBJECT】",
    }
    placeholder = placeholders.get(skill)
    if placeholder is None:
        raise ValueError(f"Unsupported skill: {skill}")

    document = Document()
    document.add_paragraph(placeholder)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_task_bytes(skill: str) -> bytes:
    payloads: dict[str, dict[str, Any]] = {
        "meeting_notice": {
            "task_type": "meeting_notice",
            "payload": {"meeting_title": "LoadTest Meeting"},
        },
        "training_notice": {
            "task_type": "training_notice",
            "payload": {"training_title": "LoadTest Training"},
        },
        "inspection_record": {
            "task_type": "inspection_record",
            "payload": {"inspection_subject": "LoadTest Site"},
        },
    }
    task = payloads.get(skill)
    if task is None:
        raise ValueError(f"Unsupported skill: {skill}")
    return json.dumps(task, ensure_ascii=False).encode("utf-8")


def _percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((p / 100) * len(ordered)) - 1))
    return ordered[index]


async def _run_single(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    skill: str,
    template_bytes: bytes,
    task_bytes: bytes,
) -> RequestResult:
    started = time.perf_counter()
    request_id: str | None = None
    subprocess_pid: int | None = None
    status_code = 599

    try:
        response = await client.post(
            f"{base_url.rstrip('/')}/v1/run",
            files={
                "template": (
                    "template.docx",
                    template_bytes,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
                "task": ("task.json", task_bytes, "application/json"),
            },
            data={"skill": skill},
        )
        status_code = response.status_code
        request_id = response.headers.get("X-Docops-Request-Id")
        if status_code == 200:
            subprocess_pid = _extract_subprocess_pid_from_zip(response.content)
        if status_code == 408 and request_id is None:
            try:
                payload = response.json()
                detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
                request_id = detail.get("request_id")
            except Exception:  # noqa: BLE001
                request_id = None
    except Exception:  # noqa: BLE001
        status_code = 599

    return RequestResult(
        status_code=status_code,
        latency_ms=int((time.perf_counter() - started) * 1000),
        request_id=request_id,
        subprocess_pid=subprocess_pid,
    )


async def _run_load_test(
    *,
    base_url: str,
    skill: str,
    concurrency: int,
    requests: int,
    timeout: float,
    check_subprocess_leaks: bool,
    leak_grace_ms: int,
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)
    template_bytes = _build_docx_bytes(skill)
    task_bytes = _build_task_bytes(skill)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def wrapped() -> RequestResult:
            async with semaphore:
                return await _run_single(
                    client,
                    base_url=base_url,
                    skill=skill,
                    template_bytes=template_bytes,
                    task_bytes=task_bytes,
                )

        tasks = [asyncio.create_task(wrapped()) for _ in range(requests)]
        results = await asyncio.gather(*tasks)

    status_counts = Counter(str(item.status_code) for item in results)
    latencies = [item.latency_ms for item in results]
    timeout_request_ids = [item.request_id for item in results if item.status_code == 408]
    subprocess_pids_seen = sorted(
        {
            item.subprocess_pid
            for item in results
            if item.status_code == 200 and isinstance(item.subprocess_pid, int)
        }
    )

    leaked_pids: list[int] = []
    pid_check_note = "skipped"
    if check_subprocess_leaks:
        await asyncio.sleep(max(0, leak_grace_ms) / 1000)
        leaked_pids = [pid for pid in subprocess_pids_seen if _pid_exists(pid)]
        pid_check_note = "checked"

    summary = {
        "base_url": base_url,
        "skill": skill,
        "requests": requests,
        "concurrency": concurrency,
        "status_counts": dict(sorted(status_counts.items())),
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "avg": int(sum(latencies) / len(latencies)) if latencies else 0,
        },
        "timeout_request_ids": [rid for rid in timeout_request_ids if rid],
        "subprocess_pids_seen": subprocess_pids_seen,
        "leaked_pids": leaked_pids,
        "leak_check": pid_check_note,
        "note": "Run against a real server process (uvicorn/gunicorn).",
    }
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local load test for docops /v1/run")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--skill", default="meeting_notice")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--check-subprocess-leaks", action="store_true")
    parser.add_argument("--leak-grace-ms", type=int, default=1500)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = asyncio.run(
        _run_load_test(
            base_url=args.base_url,
            skill=args.skill,
            concurrency=args.concurrency,
            requests=args.requests,
            timeout=args.timeout,
            check_subprocess_leaks=args.check_subprocess_leaks,
            leak_grace_ms=args.leak_grace_ms,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    leaked = summary.get("leaked_pids")
    if isinstance(leaked, list) and leaked:
        raise SystemExit(1)


def _extract_subprocess_pid_from_zip(content: bytes) -> int | None:
    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
            if "api_result.json" not in archive.namelist():
                return None
            payload = json.loads(archive.read("api_result.json").decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(payload, dict):
        return None

    subprocess_pid = payload.get("subprocess_pid")
    if isinstance(subprocess_pid, int):
        return subprocess_pid

    build = payload.get("build")
    if isinstance(build, dict):
        nested_pid = build.get("subprocess_pid")
        if isinstance(nested_pid, int):
            return nested_pid

    return None


def _pid_exists(pid: int) -> bool:
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except Exception:  # noqa: BLE001
        pass

    if pid <= 0:
        return False

    if os.name == "posix":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    if os.name == "nt" or platform.system().lower().startswith("win"):
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:  # noqa: BLE001
            return False

        output = f"{completed.stdout}\n{completed.stderr}"
        return str(pid) in output

    # Unknown platform without psutil: skip precise check.
    return False


if __name__ == "__main__":
    main()

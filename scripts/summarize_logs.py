#!/usr/bin/env python3
"""Summarize docops JSON line logs for ops/CI usage."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize docops structured logs.")
    parser.add_argument("files", nargs="+", help="One or more JSONL log files.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")
    return parser.parse_args()


def _percentile(values: list[int], p: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((p / 100) * len(ordered)) - 1))
    return ordered[index]


def summarize_log_files(paths: list[Path]) -> dict[str, Any]:
    outcome_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    queue_wait_values: list[int] = []
    total_ms_values: list[int] = []
    parse_errors = 0
    lines_total = 0

    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            parse_errors += 1
            continue

        for line in lines:
            lines_total += 1
            raw = line.strip()
            if not raw:
                continue

            try:
                payload = json.loads(raw)
            except Exception:  # noqa: BLE001
                parse_errors += 1
                continue

            if not isinstance(payload, dict):
                parse_errors += 1
                continue

            outcome = payload.get("outcome")
            if isinstance(outcome, str):
                outcome_counts[outcome] += 1

            if "http_status" in payload:
                status_counts[str(payload["http_status"])] += 1
            elif "status_code" in payload:
                status_counts[str(payload["status_code"])] += 1

            queue_wait_ms = payload.get("queue_wait_ms")
            if isinstance(queue_wait_ms, int | float):
                queue_wait_values.append(int(queue_wait_ms))

            timing = payload.get("timing")
            if isinstance(timing, dict):
                total_ms = timing.get("total_ms")
                if isinstance(total_ms, int | float):
                    total_ms_values.append(int(total_ms))

    return {
        "files": [str(path) for path in paths],
        "lines_total": lines_total,
        "parse_errors": parse_errors,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "http_status_counts": dict(sorted(status_counts.items())),
        "queue_wait_ms_p50": _percentile(queue_wait_values, 50),
        "queue_wait_ms_p95": _percentile(queue_wait_values, 95),
        "total_ms_p50": _percentile(total_ms_values, 50),
        "total_ms_p95": _percentile(total_ms_values, 95),
    }


def main() -> None:
    args = _parse_args()
    paths = [Path(item).expanduser() for item in args.files]
    summary = summarize_log_files(paths)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return

    print("DocOps Log Summary")
    print(f"files={len(summary['files'])}")
    print(f"lines_total={summary['lines_total']}")
    print(f"parse_errors={summary['parse_errors']}")
    print(f"outcome_counts={summary['outcome_counts']}")
    print(f"http_status_counts={summary['http_status_counts']}")
    print(f"queue_wait_ms_p50={summary['queue_wait_ms_p50']}")
    print(f"queue_wait_ms_p95={summary['queue_wait_ms_p95']}")
    print(f"total_ms_p50={summary['total_ms_p50']}")
    print(f"total_ms_p95={summary['total_ms_p95']}")


if __name__ == "__main__":
    main()

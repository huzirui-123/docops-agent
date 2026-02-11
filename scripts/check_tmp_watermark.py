#!/usr/bin/env python3
"""Inspect tmp directory watermark for local debugging and CI observability."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EntryStat:
    path: str
    type: str
    bytes: int


@dataclass(frozen=True)
class WatermarkStats:
    count: int
    bytes: int
    top_n: list[EntryStat]
    warnings: list[str]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check tmp watermark.")
    parser.add_argument("--root", required=True, help="Target root directory.")
    parser.add_argument("--json", action="store_true", help="Output JSON format.")
    parser.add_argument("--top-n", type=int, default=10, help="Top entry count by size.")
    return parser.parse_args()


def _directory_size(path: Path, warnings: list[str]) -> int:
    total = 0
    try:
        entries = list(path.rglob("*"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"scan_failed:{path}:{exc.__class__.__name__}")
        return 0

    for item in entries:
        try:
            if item.is_file():
                total += item.stat().st_size
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"stat_failed:{item}:{exc.__class__.__name__}")
    return total


def scan_watermark(root: Path, *, top_n: int = 10) -> WatermarkStats:
    warnings: list[str] = []
    if not root.exists():
        warnings.append(f"root_not_found:{root}")
        return WatermarkStats(count=0, bytes=0, top_n=[], warnings=warnings)

    count = 0
    total_bytes = 0
    try:
        all_entries = list(root.rglob("*"))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"scan_failed:{root}:{exc.__class__.__name__}")
        return WatermarkStats(count=0, bytes=0, top_n=[], warnings=warnings)

    for item in all_entries:
        try:
            if item.is_file():
                count += 1
                total_bytes += item.stat().st_size
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"stat_failed:{item}:{exc.__class__.__name__}")

    top_entries: list[EntryStat] = []
    try:
        children = list(root.iterdir())
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"iterdir_failed:{root}:{exc.__class__.__name__}")
        children = []

    for child in children:
        try:
            if child.is_file():
                size = child.stat().st_size
                top_entries.append(EntryStat(path=str(child), type="file", bytes=size))
            elif child.is_dir():
                size = _directory_size(child, warnings)
                top_entries.append(EntryStat(path=str(child), type="dir", bytes=size))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"child_failed:{child}:{exc.__class__.__name__}")

    top_sorted = sorted(top_entries, key=lambda item: item.bytes, reverse=True)
    return WatermarkStats(
        count=count,
        bytes=total_bytes,
        top_n=top_sorted[: max(0, top_n)],
        warnings=warnings,
    )


def _to_payload(root: Path, stats: WatermarkStats) -> dict[str, Any]:
    return {
        "root": str(root),
        "count": stats.count,
        "bytes": stats.bytes,
        "top_n": [
            {"path": item.path, "type": item.type, "bytes": item.bytes} for item in stats.top_n
        ],
        "warnings": stats.warnings,
    }


def main() -> None:
    args = _parse_args()
    root = Path(args.root).expanduser()
    stats = scan_watermark(root, top_n=args.top_n)
    payload = _to_payload(root, stats)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"root={payload['root']}")
        print(f"count={payload['count']}")
        print(f"bytes={payload['bytes']}")
        print("top_n:")
        for item in payload["top_n"]:
            print(f"  - {item['type']} {item['bytes']} {item['path']}")
        if payload["warnings"]:
            print("warnings:")
            for warning in payload["warnings"]:
                print(f"  - {warning}")


if __name__ == "__main__":
    main()

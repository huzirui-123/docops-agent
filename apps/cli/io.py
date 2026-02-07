"""CLI I/O helpers for atomic output writing."""

from __future__ import annotations

import importlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.render.models import RenderOutput

yaml = importlib.import_module("yaml")


@dataclass(frozen=True)
class OutputPaths:
    """Fixed output artifact paths for single run."""

    docx: Path
    replace_log: Path
    missing_fields: Path
    format_report: Path


def build_output_paths(out_dir: Path) -> OutputPaths:
    """Build fixed output file paths under out_dir."""

    return OutputPaths(
        docx=out_dir / "out.docx",
        replace_log=out_dir / "out.replace_log.json",
        missing_fields=out_dir / "out.missing_fields.json",
        format_report=out_dir / "out.format_report.json",
    )


def build_debug_output_path(out_dir: Path) -> Path:
    """Build optional debug dump output path under out_dir."""

    return out_dir / "out.debug.json"


def existing_output_files(paths: OutputPaths, extra_paths: list[Path] | None = None) -> list[Path]:
    """Return existing output files among fixed artifact paths."""

    candidates = [paths.docx, paths.replace_log, paths.missing_fields, paths.format_report]
    if extra_paths:
        candidates.extend(extra_paths)
    return [path for path in candidates if path.exists()]


def write_render_output_atomic(paths: OutputPaths, output: RenderOutput) -> None:
    """Write four artifacts atomically using temporary files + replace."""

    paths.docx.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_docx(paths.docx, output.document)
    _atomic_write_json(paths.replace_log, output.replace_report.model_dump(mode="json"))
    _atomic_write_json(paths.missing_fields, output.missing_fields.model_dump(mode="json"))
    _atomic_write_json(paths.format_report, output.format_report.model_dump(mode="json"))


def write_fallback_json_atomic(
    paths: OutputPaths,
    *,
    error_type: str,
    error_message: str,
    stage: str,
    docx_write_error: str | None = None,
    base_output: RenderOutput | None = None,
) -> None:
    """Write fallback JSON reports with required error metadata."""

    error_block = {
        "error_type": error_type,
        "error_message": error_message,
        "stage": stage,
        "docx_write_error": docx_write_error,
    }

    if base_output is not None:
        replace_payload = base_output.replace_report.model_dump(mode="json")
        missing_payload = base_output.missing_fields.model_dump(mode="json")
        format_payload = base_output.format_report.model_dump(mode="json")
    else:
        replace_payload = {
            "entries": [],
            "summary": {
                "total_placeholders": 0,
                "replaced_count": 0,
                "missing_count": 0,
                "had_unsupported": False,
                "unsupported_count": 0,
                "unsupported_mode": "error",
            },
            "touched_runs": [],
        }
        missing_payload = {"missing_required": [], "missing_optional": []}
        format_payload = {"passed": False, "error_count": 1, "fixed_count": 0, "issues": []}

    replace_payload = _with_error_block(replace_payload, error_block)
    missing_payload = _with_error_block(missing_payload, error_block)
    format_payload = _with_error_block(format_payload, error_block)

    paths.replace_log.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(paths.replace_log, replace_payload)
    _atomic_write_json(paths.missing_fields, missing_payload)
    _atomic_write_json(paths.format_report, format_payload)


def write_debug_dump_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write optional debug dump JSON atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, payload)


def write_suggested_policy_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write optional suggested policy YAML atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)

    fd, raw_tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    tmp_path = Path(raw_tmp_path)

    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _with_error_block(payload: dict[str, Any], error_block: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload)
    enriched["error"] = error_block
    return enriched


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f"{path.name}.",
        suffix=".tmp",
    ) as tmp:
        tmp_path = Path(tmp.name)
        json.dump(payload, tmp, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    tmp_path.replace(path)


def _atomic_write_docx(path: Path, document) -> None:
    fd, raw_tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    tmp_path = Path(raw_tmp_path)

    try:
        document.save(str(tmp_path))
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

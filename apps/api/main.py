"""FastAPI wrapper for docops generation pipeline."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import multiprocessing as mp
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from apps.api.runner_process import RunnerRequest, RunnerResponse, run_pipeline_worker
from apps.cli.io import build_output_paths
from core.format.policy_loader import load_policy
from core.skills.models import TaskSpec

app = FastAPI(title="docops-agent API", version="0.1.0")

FormatMode = Literal["report", "strict", "off"]
FormatBaseline = Literal["template", "policy"]
FormatFixMode = Literal["none", "safe"]
FormatReportMode = Literal["human", "json", "both"]
PresetMode = Literal["quick", "template", "strict"]

_DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_CONCURRENCY = 2
_DEFAULT_QUEUE_TIMEOUT_SECONDS = 0.0

_PRESET_TO_FORMAT: dict[PresetMode, tuple[FormatMode, FormatBaseline, FormatFixMode]] = {
    "quick": ("report", "template", "safe"),
    "template": ("report", "template", "none"),
    "strict": ("strict", "policy", "safe"),
}


@dataclass(frozen=True)
class EffectiveConfig:
    preset: PresetMode
    format_mode: FormatMode
    format_baseline: FormatBaseline
    format_fix_mode: FormatFixMode
    format_report: FormatReportMode


@dataclass
class _PipelineResult:
    exit_code: int
    message: str
    subprocess_pid: int | None


@dataclass
class _ConcurrencyLimiter:
    max_concurrency: int
    queue_timeout_seconds: float
    semaphore: threading.BoundedSemaphore


class ApiRequestError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.detail = detail or {}


class PipelineTimeoutError(TimeoutError):
    """Raised when subprocess execution exceeds timeout."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        pid: int | None,
        terminated: bool,
        include_pid: bool,
    ) -> None:
        detail: dict[str, Any] = {
            "timeout_seconds": timeout_seconds,
            "terminated": terminated,
        }
        if include_pid and pid is not None:
            detail["timed_out_pid"] = pid

        super().__init__("request timed out")
        self.detail = detail


_limiter_lock = threading.Lock()
_limiter_cache: _ConcurrencyLimiter | None = None


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness endpoint."""

    return {"status": "ok"}


@app.post("/v1/run", response_model=None)
async def run_v1(
    template: Annotated[UploadFile, File(...)],
    task: Annotated[UploadFile, File(...)],
    skill: Annotated[str, Form()] = "meeting_notice",
    preset: Annotated[str | None, Form()] = None,
    format_mode: Annotated[str | None, Form()] = None,
    format_baseline: Annotated[str | None, Form()] = None,
    format_fix_mode: Annotated[str | None, Form()] = None,
    format_report: Annotated[str | None, Form()] = None,
    policy_yaml: Annotated[str | None, Form()] = None,
    export_suggested_policy: Annotated[bool, Form()] = False,
) -> StreamingResponse | JSONResponse:
    """Run one generation job and return a zip with output artifacts."""

    request_started = time.perf_counter()
    request_id = uuid.uuid4().hex

    tmp_dir = Path(tempfile.mkdtemp(prefix="docops-api-run-"))
    zip_path: Path | None = None
    slot_acquired = False
    limiter: _ConcurrencyLimiter | None = None

    queue_wait_ms = 0
    subprocess_ms = 0

    try:
        limiter = _get_concurrency_limiter()
        slot_acquired, queue_wait_ms = await _try_acquire_concurrency_slot(limiter)
        if not slot_acquired:
            return _error_response(
                status_code=429,
                error_code="TOO_MANY_REQUESTS",
                message="server busy",
                request_id=request_id,
                detail={
                    "max_concurrency": limiter.max_concurrency,
                    "queue_timeout_seconds": limiter.queue_timeout_seconds,
                },
            )

        max_upload_bytes = _max_upload_bytes()
        timeout_seconds = _timeout_seconds()

        _validate_upload_name(template.filename, expected_suffix=".docx", field_name="template")
        _validate_upload_name(task.filename, expected_suffix=".json", field_name="task")

        template_path = tmp_dir / "template.docx"
        task_path = tmp_dir / "task.json"

        template_magic = _save_upload_with_limit(
            upload=template,
            destination=template_path,
            max_bytes=max_upload_bytes,
            field_name="template",
        )
        if template_magic != b"PK\x03\x04":
            raise ApiRequestError(
                status_code=415,
                error_code="INVALID_MEDIA_TYPE",
                message="template must be a valid .docx file",
                detail={"field": "template"},
            )

        _save_upload_with_limit(
            upload=task,
            destination=task_path,
            max_bytes=max_upload_bytes,
            field_name="task",
        )

        _load_task_spec(task_path)
        selected_skill_name = _resolve_skill(skill)

        effective = _resolve_effective_config(
            preset_input=preset,
            format_mode_input=format_mode,
            format_baseline_input=format_baseline,
            format_fix_mode_input=format_fix_mode,
            format_report_input=format_report,
            policy_yaml_input=policy_yaml,
        )

        policy_path: Path | None = None
        if policy_yaml is not None:
            policy_path = tmp_dir / "policy.yaml"
            policy_path.write_text(policy_yaml, encoding="utf-8")

        _load_policy_with_api_error(policy_path)

        subprocess_started = time.perf_counter()
        run_result = await _run_pipeline_with_timeout(
            timeout_seconds=timeout_seconds,
            tmp_dir=tmp_dir,
            template_path=template_path,
            task_path=task_path,
            selected_skill_name=selected_skill_name,
            policy_path=policy_path,
            effective=effective,
            export_suggested_policy=export_suggested_policy,
        )
        subprocess_ms = _elapsed_ms(subprocess_started)

        paths = build_output_paths(tmp_dir)
        api_result_path = tmp_dir / "api_result.json"
        suggested_policy_path = (
            tmp_dir / "out.suggested_policy.yaml" if export_suggested_policy else None
        )

        required_paths = [
            paths.docx,
            paths.replace_log,
            paths.missing_fields,
            paths.format_report,
        ]
        for required in required_paths:
            if not required.exists():
                raise RuntimeError(f"Missing output artifact: {required.name}")

        if suggested_policy_path is not None and not suggested_policy_path.exists():
            raise RuntimeError("Missing output artifact: out.suggested_policy.yaml")

        # First pass measures zip packaging time, second pass ships final artifacts with timing.
        trace_path = tmp_dir / "trace.json" if _debug_artifacts_enabled() else None

        timing_measure = {
            "queue_wait_ms": queue_wait_ms,
            "subprocess_ms": subprocess_ms,
            "zip_ms": 0,
            "total_ms": _elapsed_ms(request_started),
        }
        _write_json_atomic(
            api_result_path,
            _build_api_result(
                exit_code=run_result.exit_code,
                message=run_result.message,
                request_id=request_id,
                input_payload={
                    "skill": skill,
                    "preset": preset,
                    "format_mode": format_mode,
                    "format_baseline": format_baseline,
                    "format_fix_mode": format_fix_mode,
                    "format_report": format_report,
                    "policy_yaml_provided": policy_yaml is not None,
                    "export_suggested_policy": export_suggested_policy,
                },
                effective=effective,
                timing=timing_measure,
            ),
        )
        if trace_path is not None:
            _write_json_atomic(
                trace_path,
                _build_trace_payload(
                    request_id=request_id,
                    exit_code=run_result.exit_code,
                    timing=timing_measure,
                    subprocess_pid=run_result.subprocess_pid,
                    effective=effective,
                ),
            )

        optional_paths: list[Path] = []
        if suggested_policy_path is not None:
            optional_paths.append(suggested_policy_path)

        zip_started = time.perf_counter()
        measured_zip = _create_zip(required_paths + [api_result_path], optional_paths)
        measured_zip_ms = _elapsed_ms(zip_started)
        _safe_remove_file(measured_zip)

        timing_final = {
            "queue_wait_ms": queue_wait_ms,
            "subprocess_ms": subprocess_ms,
            "zip_ms": measured_zip_ms,
            "total_ms": _elapsed_ms(request_started),
        }
        _write_json_atomic(
            api_result_path,
            _build_api_result(
                exit_code=run_result.exit_code,
                message=run_result.message,
                request_id=request_id,
                input_payload={
                    "skill": skill,
                    "preset": preset,
                    "format_mode": format_mode,
                    "format_baseline": format_baseline,
                    "format_fix_mode": format_fix_mode,
                    "format_report": format_report,
                    "policy_yaml_provided": policy_yaml is not None,
                    "export_suggested_policy": export_suggested_policy,
                },
                effective=effective,
                timing=timing_final,
            ),
        )
        if trace_path is not None:
            _write_json_atomic(
                trace_path,
                _build_trace_payload(
                    request_id=request_id,
                    exit_code=run_result.exit_code,
                    timing=timing_final,
                    subprocess_pid=run_result.subprocess_pid,
                    effective=effective,
                ),
            )
            optional_paths.append(trace_path)

        zip_path = _create_zip(required_paths + [api_result_path], optional_paths)

        headers = {
            "X-Docops-Exit-Code": str(run_result.exit_code),
            "X-Docops-Request-Id": request_id,
            "Content-Disposition": 'attachment; filename="docops_outputs.zip"',
        }
        background = BackgroundTask(_cleanup_after_response, zip_path, tmp_dir)
        return StreamingResponse(
            _iter_file_chunks(zip_path),
            media_type="application/zip",
            headers=headers,
            background=background,
        )
    except ApiRequestError as exc:
        _cleanup_now(zip_path, tmp_dir)
        return _error_response(
            status_code=exc.status_code,
            error_code=exc.error_code,
            message=exc.message,
            request_id=request_id,
            detail=exc.detail,
        )
    except PipelineTimeoutError as exc:
        _cleanup_now(zip_path, tmp_dir)
        return _error_response(
            status_code=408,
            error_code="REQUEST_TIMEOUT",
            message="request timed out",
            request_id=request_id,
            detail=exc.detail,
        )
    except Exception as exc:  # noqa: BLE001
        _cleanup_now(zip_path, tmp_dir)
        return _error_response(
            status_code=500,
            error_code="INTERNAL_ERROR",
            message="internal server error",
            request_id=request_id,
            detail={"error": str(exc), "total_ms": _elapsed_ms(request_started)},
        )
    finally:
        if slot_acquired and limiter is not None:
            limiter.semaphore.release()


async def _run_pipeline_with_timeout(
    *,
    timeout_seconds: float,
    tmp_dir: Path,
    template_path: Path,
    task_path: Path,
    selected_skill_name: str,
    policy_path: Path | None,
    effective: EffectiveConfig,
    export_suggested_policy: bool,
) -> _PipelineResult:
    """Execute pipeline in subprocess and enforce hard timeout."""

    include_pid = os.getenv("DOCOPS_TEST_MODE") == "1"
    start_method = os.getenv("DOCOPS_MP_START", "spawn")
    ctx = cast(Any, mp.get_context(start_method))
    recv_conn, send_conn = ctx.Pipe(duplex=False)

    request = RunnerRequest(
        tmp_dir=str(tmp_dir),
        template_path=str(template_path),
        task_path=str(task_path),
        skill_name=selected_skill_name,
        policy_path=str(policy_path) if policy_path is not None else None,
        unsupported_mode="error",
        format_mode=effective.format_mode,
        format_baseline=effective.format_baseline,
        format_fix_mode=effective.format_fix_mode,
        export_suggested_policy=export_suggested_policy,
    )
    process = ctx.Process(
        target=run_pipeline_worker,
        args=(request, send_conn),
        name="docops-api-runner",
        daemon=True,
    )

    try:
        process.start()
    finally:
        send_conn.close()

    deadline = time.monotonic() + timeout_seconds
    response_payload: RunnerResponse | None = None

    try:
        while True:
            if recv_conn.poll(0.0):
                response_payload = cast(RunnerResponse, recv_conn.recv())
                break
            if not process.is_alive():
                break
            if time.monotonic() >= deadline:
                terminated = _terminate_process(process)
                raise PipelineTimeoutError(
                    timeout_seconds=timeout_seconds,
                    pid=process.pid,
                    terminated=terminated,
                    include_pid=include_pid,
                )
            await asyncio.sleep(0.01)

        if response_payload is None and recv_conn.poll(0.0):
            response_payload = cast(RunnerResponse, recv_conn.recv())

        process.join(timeout=0.5)
        if process.is_alive():
            _terminate_process(process)
            raise RuntimeError("Runner subprocess did not exit cleanly")

        if response_payload is None:
            raise RuntimeError("Runner subprocess exited without a response payload")

        if not response_payload.ok:
            error_type = response_payload.error_type
            error_message = response_payload.error_message
            raise RuntimeError(
                f"Runner subprocess failed: {error_type}: {error_message}"
            )

        if response_payload.exit_code is None:
            raise RuntimeError("Runner subprocess returned no exit_code")

        return _PipelineResult(
            exit_code=response_payload.exit_code,
            message=response_payload.message,
            subprocess_pid=process.pid,
        )
    finally:
        try:
            recv_conn.close()
        finally:
            if process.is_alive():
                _terminate_process(process)


def _terminate_process(process: mp.Process) -> bool:
    """Terminate/kill subprocess and wait for exit."""

    if not process.is_alive():
        return True

    process.terminate()
    process.join(timeout=0.5)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.5)

    return not process.is_alive()


def _resolve_effective_config(
    *,
    preset_input: str | None,
    format_mode_input: str | None,
    format_baseline_input: str | None,
    format_fix_mode_input: str | None,
    format_report_input: str | None,
    policy_yaml_input: str | None,
) -> EffectiveConfig:
    advanced_explicit = any(
        value is not None
        for value in (
            format_mode_input,
            format_baseline_input,
            format_fix_mode_input,
            format_report_input,
            policy_yaml_input,
        )
    )

    if preset_input is not None and advanced_explicit:
        raise ApiRequestError(
            status_code=400,
            error_code="INVALID_ARGUMENT_CONFLICT",
            message="preset cannot be combined with advanced format arguments",
            detail={
                "conflicting_fields": [
                    name
                    for name, value in (
                        ("format_mode", format_mode_input),
                        ("format_baseline", format_baseline_input),
                        ("format_fix_mode", format_fix_mode_input),
                        ("format_report", format_report_input),
                        ("policy_yaml", policy_yaml_input),
                    )
                    if value is not None
                ]
            },
        )

    preset_value = _normalize_or_default(
        value=preset_input,
        default="quick",
        field_name="preset",
        allowed={"quick", "template", "strict"},
    )
    preset = cast(PresetMode, preset_value)
    base_mode, base_baseline, base_fix_mode = _PRESET_TO_FORMAT[preset]

    mode = cast(
        FormatMode,
        _normalize_or_default(
            value=format_mode_input,
            default=base_mode,
            field_name="format_mode",
            allowed={"report", "strict", "off"},
        ),
    )
    baseline = cast(
        FormatBaseline,
        _normalize_or_default(
            value=format_baseline_input,
            default=base_baseline,
            field_name="format_baseline",
            allowed={"template", "policy"},
        ),
    )
    fix_mode = cast(
        FormatFixMode,
        _normalize_or_default(
            value=format_fix_mode_input,
            default=base_fix_mode,
            field_name="format_fix_mode",
            allowed={"none", "safe"},
        ),
    )

    # API defaults to quiet mode unless explicitly provided.
    report_mode = cast(
        FormatReportMode,
        _normalize_or_default(
            value=format_report_input,
            default="json",
            field_name="format_report",
            allowed={"human", "json", "both"},
        ),
    )

    return EffectiveConfig(
        preset=preset,
        format_mode=mode,
        format_baseline=baseline,
        format_fix_mode=fix_mode,
        format_report=report_mode,
    )


def _normalize_or_default(
    *,
    value: str | None,
    default: str,
    field_name: str,
    allowed: set[str],
) -> str:
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized not in allowed:
        raise ApiRequestError(
            status_code=400,
            error_code="INVALID_ARGUMENT",
            message=f"invalid {field_name}",
            detail={"field": field_name, "value": value, "allowed": sorted(allowed)},
        )
    return normalized


def _load_task_spec(task_path: Path) -> TaskSpec:
    try:
        task_raw = json.loads(task_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApiRequestError(
            status_code=400,
            error_code="INVALID_JSON",
            message="task file must be valid JSON",
            detail={"field": "task", "error": str(exc)},
        ) from exc
    except UnicodeDecodeError as exc:
        raise ApiRequestError(
            status_code=400,
            error_code="INVALID_JSON",
            message="task file must be UTF-8 JSON",
            detail={"field": "task"},
        ) from exc

    if not isinstance(task_raw, dict):
        raise ApiRequestError(
            status_code=400,
            error_code="INVALID_JSON",
            message="task JSON must be an object",
            detail={"field": "task"},
        )

    try:
        return TaskSpec.model_validate(task_raw)
    except ValidationError as exc:
        raise ApiRequestError(
            status_code=400,
            error_code="INVALID_ARGUMENT",
            message="task JSON schema validation failed",
            detail={"field": "task", "error": str(exc)},
        ) from exc


def _resolve_skill(skill_name: str) -> str:
    if skill_name == "meeting_notice":
        return skill_name
    raise ApiRequestError(
        status_code=400,
        error_code="INVALID_ARGUMENT",
        message="unsupported skill",
        detail={"field": "skill", "value": skill_name},
    )


def _load_policy_with_api_error(policy_path: Path | None):
    try:
        return load_policy(policy_path)
    except ValueError as exc:
        raise ApiRequestError(
            status_code=400,
            error_code="INVALID_ARGUMENT",
            message="invalid policy_yaml",
            detail={"field": "policy_yaml", "error": str(exc)},
        ) from exc


def _validate_upload_name(filename: str | None, *, expected_suffix: str, field_name: str) -> None:
    if filename is None or not filename.lower().endswith(expected_suffix):
        raise ApiRequestError(
            status_code=415,
            error_code="INVALID_MEDIA_TYPE",
            message=f"{field_name} must be a {expected_suffix} file",
            detail={"field": field_name, "filename": filename},
        )


def _save_upload_with_limit(
    *,
    upload: UploadFile,
    destination: Path,
    max_bytes: int,
    field_name: str,
) -> bytes:
    destination.parent.mkdir(parents=True, exist_ok=True)

    total_size = 0
    magic = b""

    source = upload.file
    source.seek(0)

    with destination.open("wb") as handle:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            if len(magic) < 4:
                magic = (magic + chunk)[:4]

            total_size += len(chunk)
            if total_size > max_bytes:
                raise ApiRequestError(
                    status_code=413,
                    error_code="UPLOAD_TOO_LARGE",
                    message=f"{field_name} exceeds upload size limit",
                    detail={
                        "field": field_name,
                        "max_bytes": max_bytes,
                        "received_bytes": total_size,
                    },
                )
            handle.write(chunk)

    source.close()
    return magic


def _max_upload_bytes() -> int:
    raw = os.getenv("DOCOPS_MAX_UPLOAD_BYTES")
    if raw is None:
        return _DEFAULT_MAX_UPLOAD_BYTES
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_MAX_UPLOAD_BYTES
    return parsed if parsed > 0 else _DEFAULT_MAX_UPLOAD_BYTES


def _timeout_seconds() -> float:
    raw = os.getenv("DOCOPS_REQUEST_TIMEOUT_SECONDS")
    if raw is None:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS
    return parsed if parsed > 0 else _DEFAULT_TIMEOUT_SECONDS


def _max_concurrency() -> int:
    raw = os.getenv("DOCOPS_MAX_CONCURRENCY")
    if raw is None:
        return _DEFAULT_MAX_CONCURRENCY
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_MAX_CONCURRENCY
    return parsed if parsed > 0 else _DEFAULT_MAX_CONCURRENCY


def _queue_timeout_seconds() -> float:
    raw = os.getenv("DOCOPS_QUEUE_TIMEOUT_SECONDS")
    if raw is None:
        return _DEFAULT_QUEUE_TIMEOUT_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return _DEFAULT_QUEUE_TIMEOUT_SECONDS
    return parsed if parsed >= 0 else _DEFAULT_QUEUE_TIMEOUT_SECONDS


def _get_concurrency_limiter() -> _ConcurrencyLimiter:
    global _limiter_cache

    max_concurrency = _max_concurrency()
    queue_timeout = _queue_timeout_seconds()

    with _limiter_lock:
        if _limiter_cache is None:
            _limiter_cache = _ConcurrencyLimiter(
                max_concurrency=max_concurrency,
                queue_timeout_seconds=queue_timeout,
                semaphore=threading.BoundedSemaphore(value=max_concurrency),
            )
            return _limiter_cache

        if (
            _limiter_cache.max_concurrency != max_concurrency
            or _limiter_cache.queue_timeout_seconds != queue_timeout
        ):
            _limiter_cache = _ConcurrencyLimiter(
                max_concurrency=max_concurrency,
                queue_timeout_seconds=queue_timeout,
                semaphore=threading.BoundedSemaphore(value=max_concurrency),
            )

        return _limiter_cache


async def _try_acquire_concurrency_slot(limiter: _ConcurrencyLimiter) -> tuple[bool, int]:
    waited_started = time.perf_counter()
    timeout_seconds = limiter.queue_timeout_seconds

    if timeout_seconds == 0:
        acquired_now = limiter.semaphore.acquire(blocking=False)
        return acquired_now, _elapsed_ms(waited_started)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if limiter.semaphore.acquire(blocking=False):
            return True, _elapsed_ms(waited_started)
        await asyncio.sleep(0.01)

    return False, _elapsed_ms(waited_started)


def _debug_artifacts_enabled() -> bool:
    return os.getenv("DOCOPS_DEBUG_ARTIFACTS", "0") == "1"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _create_zip(required_paths: list[Path], optional_paths: list[Path]) -> Path:
    fd, raw_zip = tempfile.mkstemp(prefix="docops-api-zip-", suffix=".zip")
    os.close(fd)
    zip_path = Path(raw_zip)

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for artifact in required_paths:
            archive.write(artifact, arcname=artifact.name)
        for artifact in optional_paths:
            if artifact.exists():
                archive.write(artifact, arcname=artifact.name)

    return zip_path


def _build_api_result(
    *,
    exit_code: int,
    message: str,
    request_id: str,
    input_payload: dict[str, Any],
    effective: EffectiveConfig,
    timing: dict[str, int],
) -> dict[str, Any]:
    return {
        "exit_code": exit_code,
        "message": message,
        "request_id": request_id,
        "timing": timing,
        "input": input_payload,
        "effective": {
            "preset": effective.preset,
            "format_mode": effective.format_mode,
            "format_baseline": effective.format_baseline,
            "format_fix_mode": effective.format_fix_mode,
            "format_report": effective.format_report,
        },
        "build": {
            "version": _package_version(),
            "commit": os.getenv("DOCOPS_COMMIT_SHA", "unknown"),
        },
    }


def _build_trace_payload(
    *,
    request_id: str,
    exit_code: int,
    timing: dict[str, int],
    subprocess_pid: int | None,
    effective: EffectiveConfig,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "exit_code": exit_code,
        "timing": timing,
        "subprocess": {
            "pid": subprocess_pid,
            "start_method": os.getenv("DOCOPS_MP_START", "spawn"),
        },
        "effective": {
            "preset": effective.preset,
            "format_mode": effective.format_mode,
            "format_baseline": effective.format_baseline,
            "format_fix_mode": effective.format_fix_mode,
            "format_report": effective.format_report,
        },
    }


def _package_version() -> str:
    try:
        return importlib.metadata.version("docops-agent")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _error_response(
    *,
    status_code: int,
    error_code: str,
    message: str,
    request_id: str,
    detail: dict[str, Any] | None = None,
) -> JSONResponse:
    payload_detail = dict(detail or {})
    payload_detail["request_id"] = request_id

    return JSONResponse(
        status_code=status_code,
        headers={"X-Docops-Request-Id": request_id},
        content={
            "error_code": error_code,
            "message": message,
            "detail": payload_detail,
        },
    )


async def _iter_file_chunks(path: Path, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while True:
            data = handle.read(chunk_size)
            if not data:
                break
            yield data
            await asyncio.sleep(0)


def _cleanup_now(zip_path: Path | None, tmp_dir: Path) -> None:
    if zip_path is not None:
        _safe_remove_file(zip_path)
    _safe_remove_dir(tmp_dir)


async def _cleanup_after_response(zip_path: Path, tmp_dir: Path) -> None:
    """Cleanup generated temp artifacts after response is sent."""

    _safe_remove_file(zip_path)
    _safe_remove_dir(tmp_dir)


def _safe_remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def _safe_remove_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)

"""FastAPI wrapper for docops generation pipeline."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import importlib.metadata
import json
import logging
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
from typing import Annotated, Any, Literal, cast, get_args, get_origin

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from apps.api.runner_process import RunnerRequest, RunnerResponse, run_pipeline_worker
from apps.cli.io import build_output_paths
from core.format.policy_loader import load_policy
from core.skills.models import TASK_PAYLOAD_SCHEMAS, TaskSpec, supported_task_types
from core.skills.registry import create_skill, list_supported_skills

app = FastAPI(title="docops-agent API", version="0.1.0")
logger = logging.getLogger("docops.api")

FormatMode = Literal["report", "strict", "off"]
FormatBaseline = Literal["template", "policy"]
FormatFixMode = Literal["none", "safe"]
FormatReportMode = Literal["human", "json", "both"]
PresetMode = Literal["quick", "template", "strict"]

_DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_CONCURRENCY = 2
_DEFAULT_QUEUE_TIMEOUT_SECONDS = 0.0
_BASIC_AUTH_REALM = "docops"

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


@dataclass(frozen=True)
class _ZipBuildResult:
    zip_path: Path
    timing: dict[str, int]


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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Ensure every response has a request id header."""

    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001
        _log_event(
            logging.ERROR,
            "error",
            request_id,
            error_code="INTERNAL_ERROR",
            status_code=500,
            failure_stage="middleware",
        )
        response = _error_response(
            status_code=500,
            error_code="INTERNAL_ERROR",
            message="internal server error",
            request_id=request_id,
            detail={"path": request.url.path},
        )
    response.headers.setdefault("X-Docops-Request-Id", request_id)
    return response


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness endpoint."""

    return {"status": "ok"}


@app.get("/v1/meta")
async def meta_v1(request: Request) -> JSONResponse:
    """Metadata endpoint for web/bootstrap clients."""

    request_id = _request_id_from_request(request)
    auth_error = _guard_meta_access(request, request_id)
    if auth_error is not None:
        return auth_error

    payload = {
        "supported_skills": list_supported_skills(),
        "supported_task_types": supported_task_types(),
        "supported_presets": list(_PRESET_TO_FORMAT),
        "task_payload_schemas": _task_payload_summaries(),
        "version": app.version,
    }
    return JSONResponse(
        status_code=200,
        headers={"X-Docops-Request-Id": request_id},
        content=payload,
    )


@app.get("/web", response_model=None)
async def web_console(request: Request) -> HTMLResponse | JSONResponse:
    """Built-in web console entry point."""

    request_id = _request_id_from_request(request)
    auth_error = _guard_web_console_access(request, request_id)
    if auth_error is not None:
        return auth_error

    html_path = Path(__file__).resolve().parent / "static" / "web_console.html"
    html = html_path.read_text(encoding="utf-8")
    return HTMLResponse(
        content=html,
        headers={"X-Docops-Request-Id": request_id},
    )


@app.post("/v1/run", response_model=None)
async def run_v1(
    request: Request,
    template: Annotated[UploadFile, File(...)],
    task: Annotated[UploadFile, File(...)],
    skill: Annotated[str, Form()] = "meeting_notice",
    preset: Annotated[str | None, Form()] = None,
    strict: Annotated[bool | None, Form()] = None,
    format_mode: Annotated[str | None, Form()] = None,
    format_baseline: Annotated[str | None, Form()] = None,
    format_fix_mode: Annotated[str | None, Form()] = None,
    format_report: Annotated[str | None, Form()] = None,
    policy_yaml: Annotated[str | None, Form()] = None,
    export_suggested_policy: Annotated[bool, Form()] = False,
) -> StreamingResponse | JSONResponse:
    """Run one generation job and return a zip with output artifacts."""

    request_started = time.perf_counter()
    request_id = _request_id_from_request(request)
    failure_stage = "init"

    tmp_dir = Path(tempfile.mkdtemp(prefix="docops-api-run-"))
    zip_path: Path | None = None
    slot_acquired = False
    limiter: _ConcurrencyLimiter | None = None

    queue_wait_ms = 0
    subprocess_ms = 0

    try:
        failure_stage = "validate_inputs"
        limiter = _get_concurrency_limiter()
        slot_acquired, queue_wait_ms = await _try_acquire_concurrency_slot(limiter)
        if not slot_acquired:
            _log_event(
                logging.ERROR,
                "error",
                request_id,
                error_code="TOO_MANY_REQUESTS",
                status_code=429,
                failure_stage=failure_stage,
                queue_wait_ms=queue_wait_ms,
            )
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

        failure_stage = "upload"
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

        failure_stage = "validate_task"
        task_spec = _load_task_spec(task_path)

        failure_stage = "validate_inputs"
        effective = _resolve_effective_config(
            preset_input=preset,
            strict_input=strict,
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

        _log_event(
            logging.INFO,
            "start",
            request_id,
            skill=skill,
            task_type=task_spec.task_type,
            preset_input=preset,
            effective={
                "preset": effective.preset,
                "format_mode": effective.format_mode,
                "format_baseline": effective.format_baseline,
                "format_fix_mode": effective.format_fix_mode,
                "format_report": effective.format_report,
            },
            max_upload_bytes=max_upload_bytes,
            timeout_seconds=timeout_seconds,
            queue_wait_ms=queue_wait_ms,
            policy_yaml_provided=policy_yaml is not None,
        )

        failure_stage = "validate_skill"
        selected_skill_name = _resolve_skill(skill)
        if selected_skill_name != task_spec.task_type:
            raise ApiRequestError(
                status_code=400,
                error_code="INVALID_ARGUMENT_CONFLICT",
                message="skill and task_type must match",
                detail={
                    "field": "skill",
                    "skill": selected_skill_name,
                    "task_type": task_spec.task_type,
                },
            )

        failure_stage = "run_subprocess"
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

        failure_stage = "package_zip"
        timing_payload = {
            "queue_wait_ms": queue_wait_ms,
            "subprocess_ms": subprocess_ms,
            "zip_ms": 0,
            "total_ms": _elapsed_ms(request_started),
        }
        api_result_payload = _build_api_result(
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
            timing=timing_payload,
        )
        trace_payload = (
            _build_trace_payload(
                request_id=request_id,
                exit_code=run_result.exit_code,
                timing=timing_payload,
                subprocess_pid=run_result.subprocess_pid,
                effective=effective,
            )
            if _debug_artifacts_enabled()
            else None
        )

        optional_paths: list[Path] = []
        if suggested_policy_path is not None:
            optional_paths.append(suggested_policy_path)

        zip_result = _create_zip_with_metadata(
            required_paths=required_paths,
            optional_paths=optional_paths,
            api_result_payload=api_result_payload,
            trace_payload=trace_payload,
            request_started=request_started,
        )
        zip_path = zip_result.zip_path

        failure_stage = "respond"
        _log_event(
            logging.INFO,
            "done",
            request_id,
            exit_code=run_result.exit_code,
            timing=zip_result.timing,
            subprocess_pid=run_result.subprocess_pid,
            debug_trace_enabled=trace_payload is not None,
        )
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
        _log_event(
            logging.ERROR,
            "error",
            request_id,
            error_code=exc.error_code,
            status_code=exc.status_code,
            failure_stage=failure_stage,
        )
        _cleanup_now(zip_path, tmp_dir)
        return _error_response(
            status_code=exc.status_code,
            error_code=exc.error_code,
            message=exc.message,
            request_id=request_id,
            detail=exc.detail,
        )
    except PipelineTimeoutError as exc:
        _log_event(
            logging.ERROR,
            "error",
            request_id,
            error_code="REQUEST_TIMEOUT",
            status_code=408,
            failure_stage=failure_stage,
        )
        _cleanup_now(zip_path, tmp_dir)
        return _error_response(
            status_code=408,
            error_code="REQUEST_TIMEOUT",
            message="request timed out",
            request_id=request_id,
            detail=exc.detail,
        )
    except Exception as exc:  # noqa: BLE001
        _log_event(
            logging.ERROR,
            "error",
            request_id,
            error_code="INTERNAL_ERROR",
            status_code=500,
            failure_stage=failure_stage,
        )
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
    strict_input: bool | None,
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

    if strict_input is not None and any(
        value is not None
        for value in (
            format_mode_input,
            format_baseline_input,
            format_fix_mode_input,
            format_report_input,
        )
    ):
        raise ApiRequestError(
            status_code=400,
            error_code="INVALID_ARGUMENT_CONFLICT",
            message="strict cannot be combined with explicit format_* arguments",
            detail={
                "conflicting_fields": [
                    name
                    for name, value in (
                        ("format_mode", format_mode_input),
                        ("format_baseline", format_baseline_input),
                        ("format_fix_mode", format_fix_mode_input),
                        ("format_report", format_report_input),
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

    if strict_input is True:
        mode = "strict"

    return EffectiveConfig(
        preset=preset,
        format_mode=mode,
        format_baseline=baseline,
        format_fix_mode=fix_mode,
        format_report=report_mode,
    )


def _request_id_from_request(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    generated = uuid.uuid4().hex
    request.state.request_id = generated
    return generated


def _guard_web_console_access(request: Request, request_id: str) -> JSONResponse | None:
    if not _web_console_enabled():
        return _error_response(
            status_code=404,
            error_code="NOT_FOUND",
            message="web console is disabled",
            request_id=request_id,
            detail={"path": request.url.path},
        )

    auth_error = _basic_auth_error_response_if_needed(request, request_id)
    if auth_error is not None:
        return auth_error
    return None


def _guard_meta_access(request: Request, request_id: str) -> JSONResponse | None:
    if not _meta_enabled():
        return _error_response(
            status_code=404,
            error_code="NOT_FOUND",
            message="meta endpoint is disabled",
            request_id=request_id,
            detail={"path": request.url.path},
        )

    auth_error = _basic_auth_error_response_if_needed(request, request_id)
    if auth_error is not None:
        return auth_error
    return None


def _web_console_enabled() -> bool:
    raw = os.getenv("DOCOPS_ENABLE_WEB_CONSOLE", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _meta_enabled() -> bool:
    raw = os.getenv("DOCOPS_ENABLE_META", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _basic_auth_error_response_if_needed(request: Request, request_id: str) -> JSONResponse | None:
    expected = _basic_auth_credentials()
    if expected is None:
        return None

    if _request_has_valid_basic_auth(request, expected):
        return None

    return _error_response(
        status_code=401,
        error_code="UNAUTHORIZED",
        message="authentication required",
        request_id=request_id,
        detail={
            "path": request.url.path,
            "auth_enabled": True,
        },
        extra_headers={"WWW-Authenticate": f'Basic realm="{_BASIC_AUTH_REALM}"'},
    )


def _basic_auth_credentials() -> tuple[str, str] | None:
    raw = os.getenv("DOCOPS_WEB_BASIC_AUTH")
    if raw is None:
        return None

    candidate = raw.strip()
    if not candidate:
        return None

    if ":" not in candidate:
        return None

    username, password = candidate.split(":", 1)
    if not username or not password:
        return None
    return username, password


def _request_has_valid_basic_auth(request: Request, expected: tuple[str, str]) -> bool:
    auth_header = request.headers.get("authorization")
    if auth_header is None:
        return False

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return False

    try:
        decoded = base64.b64decode(token.encode("ascii"), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False

    if ":" not in decoded:
        return False
    username, password = decoded.split(":", 1)
    expected_username, expected_password = expected
    return hmac.compare_digest(username, expected_username) and hmac.compare_digest(
        password, expected_password
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
    try:
        create_skill(skill_name)
    except ValueError as exc:
        raise ApiRequestError(
            status_code=400,
            error_code="INVALID_ARGUMENT",
            message="unsupported skill",
            detail={
                "field": "skill",
                "value": skill_name,
                "supported_skills": list_supported_skills(),
            },
        ) from exc
    return skill_name


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


def _create_zip_with_metadata(
    *,
    required_paths: list[Path],
    optional_paths: list[Path],
    api_result_payload: dict[str, Any],
    trace_payload: dict[str, Any] | None,
    request_started: float,
) -> _ZipBuildResult:
    """Create one zip archive with artifacts and embedded API metadata."""

    fd, raw_zip = tempfile.mkstemp(prefix="docops-api-zip-", suffix=".zip")
    os.close(fd)
    zip_path = Path(raw_zip)

    zip_started = time.perf_counter()
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for artifact in required_paths:
            archive.write(artifact, arcname=artifact.name)
        for artifact in optional_paths:
            if artifact.exists():
                archive.write(artifact, arcname=artifact.name)

        zip_ms = _elapsed_ms(zip_started)
        total_ms = _elapsed_ms(request_started)
        archive.writestr(
            "api_result.json",
            _dump_json(
                _with_timing(
                    api_result_payload,
                    zip_ms=zip_ms,
                    total_ms=total_ms,
                )
            ),
        )

        if trace_payload is not None:
            archive.writestr(
                "trace.json",
                _dump_json(
                    _with_timing(
                        trace_payload,
                        zip_ms=zip_ms,
                        total_ms=total_ms,
                    )
                ),
            )

    final_timing = _with_timing(
        api_result_payload,
        zip_ms=zip_ms,
        total_ms=total_ms,
    ).get("timing")
    timing_dict = (
        cast(dict[str, int], final_timing)
        if isinstance(final_timing, dict)
        else {"zip_ms": zip_ms, "total_ms": total_ms}
    )
    return _ZipBuildResult(zip_path=zip_path, timing=timing_dict)


def _with_timing(payload: dict[str, Any], *, zip_ms: int, total_ms: int) -> dict[str, Any]:
    """Copy payload and override zip/total timing fields."""

    updated = dict(payload)
    timing_raw = updated.get("timing")
    timing = dict(timing_raw) if isinstance(timing_raw, dict) else {}
    timing["zip_ms"] = zip_ms
    timing["total_ms"] = total_ms
    updated["timing"] = timing
    return updated


def _dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload_detail = dict(detail or {})
    payload_detail["request_id"] = request_id

    headers = {"X-Docops-Request-Id": request_id}
    if extra_headers is not None:
        headers.update(extra_headers)

    return JSONResponse(
        status_code=status_code,
        headers=headers,
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


def _log_event(level: int, event: str, request_id: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "request_id": request_id,
        **fields,
    }
    logger.log(level, _dump_json(payload))


def _task_payload_summaries() -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for task_type in supported_task_types():
        payload_model = TASK_PAYLOAD_SCHEMAS[task_type]
        fields: dict[str, dict[str, Any]] = {}
        for field_name in sorted(payload_model.model_fields):
            model_field = payload_model.model_fields[field_name]
            annotation = model_field.annotation
            fields[field_name] = {
                "type": _annotation_to_type(annotation),
                "required": model_field.is_required(),
                "nullable": _annotation_is_nullable(annotation),
            }

        extra_policy = payload_model.model_config.get("extra")
        summaries[task_type] = {
            "fields": fields,
            "extra_policy": str(extra_policy) if extra_policy is not None else "allow",
        }
    return summaries


def _annotation_is_nullable(annotation: Any) -> bool:
    if annotation is None or annotation is type(None):
        return True
    origin = get_origin(annotation)
    if origin is None:
        return False
    return any(_annotation_is_nullable(arg) for arg in get_args(annotation))


def _annotation_to_type(annotation: Any) -> str:
    if annotation is None or annotation is type(None):
        return "none"
    origin = get_origin(annotation)
    if origin is None:
        name = getattr(annotation, "__name__", str(annotation))
        if name.lower().startswith("strict"):
            name = name[len("strict") :]
        return name.lower()

    if origin is list:
        args = get_args(annotation)
        inner = _annotation_to_type(args[0]) if args else "any"
        return f"list[{inner}]"
    if origin is dict:
        args = get_args(annotation)
        if len(args) == 2:
            return f"dict[{_annotation_to_type(args[0])},{_annotation_to_type(args[1])}]"
        return "dict"
    if origin is tuple:
        tuple_args = ",".join(_annotation_to_type(arg) for arg in get_args(annotation))
        return f"tuple[{tuple_args}]"

    # Covers unions (including PEP 604) and other typing wrappers.
    union_args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if union_args:
        if len(union_args) == 1:
            return _annotation_to_type(union_args[0])
        return " | ".join(_annotation_to_type(arg) for arg in union_args)

    origin_name = getattr(origin, "__name__", str(origin))
    return origin_name.lower()

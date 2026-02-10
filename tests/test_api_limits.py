from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import httpx
import pytest
from docx import Document

from apps.api.main import app


def _build_docx_bytes() -> bytes:
    document = Document()
    document.add_paragraph("【MEETING_TITLE】")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _task_bytes() -> bytes:
    payload = {"task_type": "meeting_notice", "payload": {"meeting_title": "Kickoff"}}
    return json.dumps(payload).encode("utf-8")


@pytest.mark.anyio
async def test_run_upload_too_large_returns_413(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCOPS_MAX_UPLOAD_BYTES", "32")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/run",
            files={
                "template": (
                    "template.docx",
                    _build_docx_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
                "task": ("task.json", _task_bytes(), "application/json"),
            },
            data={"skill": "meeting_notice"},
        )

    assert response.status_code == 413
    payload = response.json()
    assert payload["error_code"] == "UPLOAD_TOO_LARGE"
    assert payload["detail"]["request_id"] == response.headers["X-Docops-Request-Id"]


@pytest.mark.anyio
async def test_run_timeout_returns_408(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCOPS_REQUEST_TIMEOUT_SECONDS", "0.1")
    monkeypatch.setenv("DOCOPS_TEST_MODE", "1")
    monkeypatch.setenv("DOCOPS_TEST_SLEEP_SECONDS", "10")
    monkeypatch.setenv("DOCOPS_MP_START", "spawn")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/run",
            files={
                "template": (
                    "template.docx",
                    _build_docx_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
                "task": ("task.json", _task_bytes(), "application/json"),
            },
            data={"skill": "meeting_notice"},
        )

    assert response.status_code == 408
    payload = response.json()
    assert payload["error_code"] == "REQUEST_TIMEOUT"
    assert payload["detail"]["request_id"] == response.headers["X-Docops-Request-Id"]
    detail = payload["detail"]
    assert detail["terminated"] is True
    pid = detail.get("timed_out_pid")
    assert isinstance(pid, int)

    if sys.platform.startswith("linux"):
        deadline = time.monotonic() + 1.0
        while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not Path(f"/proc/{pid}").exists()

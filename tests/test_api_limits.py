from __future__ import annotations

import io
import json

import httpx
import pytest
from docx import Document

import apps.api.main as api_main
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
async def test_run_upload_too_large_returns_413(monkeypatch) -> None:
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


@pytest.mark.anyio
async def test_run_timeout_returns_408(monkeypatch) -> None:
    monkeypatch.setenv("DOCOPS_REQUEST_TIMEOUT_SECONDS", "0.001")

    def _fake_timeout(**kwargs):  # noqa: ANN003
        raise TimeoutError

    monkeypatch.setattr(api_main, "_run_pipeline_with_timeout", _fake_timeout)
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

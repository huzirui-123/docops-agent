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
async def test_run_returns_429_when_concurrency_slot_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCOPS_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("DOCOPS_QUEUE_TIMEOUT_SECONDS", "0")

    async def _fake_try_acquire(limiter):  # noqa: ANN001
        return False, 0

    monkeypatch.setattr(api_main, "_try_acquire_concurrency_slot", _fake_try_acquire)

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

    assert response.status_code == 429
    assert response.headers["X-Docops-Request-Id"]

    payload = response.json()
    assert payload["error_code"] == "TOO_MANY_REQUESTS"
    assert payload["detail"]["max_concurrency"] == 1
    assert payload["detail"]["queue_timeout_seconds"] == 0
    assert payload["detail"]["request_id"] == response.headers["X-Docops-Request-Id"]

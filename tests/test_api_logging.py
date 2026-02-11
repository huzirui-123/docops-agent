from __future__ import annotations

import io
import json
import logging

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


@pytest.mark.anyio
async def test_api_logs_request_id_for_success(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="docops.api")
    task_payload = {"task_type": "meeting_notice", "payload": {"meeting_title": "Kickoff"}}

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
                "task": ("task.json", json.dumps(task_payload).encode("utf-8"), "application/json"),
            },
            data={"skill": "meeting_notice"},
        )

    assert response.status_code == 200
    request_id = response.headers["X-Docops-Request-Id"]
    messages = [record.message for record in caplog.records if record.name == "docops.api"]
    assert any('"event":"start"' in message and request_id in message for message in messages)
    assert any('"event":"done"' in message and request_id in message for message in messages)


@pytest.mark.anyio
async def test_api_logs_request_id_and_error_code_for_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="docops.api")
    task_payload = {"task_type": "meeting_notice", "payload": {"meeting_title": "Kickoff"}}

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
                "task": ("task.json", json.dumps(task_payload).encode("utf-8"), "application/json"),
            },
            data={"skill": "training_notice"},
        )

    assert response.status_code == 400
    request_id = response.headers["X-Docops-Request-Id"]
    messages = [record.message for record in caplog.records if record.name == "docops.api"]
    assert any(
        '"event":"error"' in message
        and request_id in message
        and '"error_code":"INVALID_ARGUMENT_CONFLICT"' in message
        and '"failure_stage":"validate_skill"' in message
        for message in messages
    )

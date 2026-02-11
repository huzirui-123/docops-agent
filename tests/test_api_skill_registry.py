from __future__ import annotations

import io
import json
import zipfile

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


def _zip_map(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.anyio
async def test_api_unsupported_skill_returns_supported_list() -> None:
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
            data={"skill": "unknown_skill"},
        )

    assert response.status_code == 400
    request_id = response.headers["X-Docops-Request-Id"]
    payload = response.json()
    assert payload["error_code"] == "INVALID_ARGUMENT"
    assert {
        "meeting_notice",
        "training_notice",
        "inspection_record",
    }.issubset(set(payload["detail"]["supported_skills"]))
    assert payload["detail"]["request_id"] == request_id


@pytest.mark.anyio
async def test_api_supported_skill_still_runs_successfully() -> None:
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

    assert response.status_code == 200
    assert response.headers["X-Docops-Exit-Code"] == "0"
    request_id = response.headers["X-Docops-Request-Id"]

    zipped = _zip_map(response.content)
    api_result = json.loads(zipped["api_result.json"].decode("utf-8"))
    assert api_result["request_id"] == request_id
    assert api_result["effective"]["preset"] == "quick"


@pytest.mark.anyio
async def test_api_skill_task_type_mismatch_returns_conflict() -> None:
    task_payload = {"task_type": "meeting_notice", "payload": {"meeting_title": "Kickoff"}}
    task_bytes = json.dumps(task_payload).encode("utf-8")
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
                "task": ("task.json", task_bytes, "application/json"),
            },
            data={"skill": "training_notice"},
        )

    assert response.status_code == 400
    request_id = response.headers["X-Docops-Request-Id"]
    payload = response.json()
    assert payload["error_code"] == "INVALID_ARGUMENT_CONFLICT"
    assert payload["detail"]["request_id"] == request_id
    assert payload["detail"]["skill"] == "training_notice"
    assert payload["detail"]["task_type"] == "meeting_notice"

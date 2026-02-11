from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest
from docx import Document

from apps.api.main import app


def _build_docx_bytes(placeholder: str) -> bytes:
    document = Document()
    document.add_paragraph(placeholder)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _zip_map(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _assert_timing(payload: dict[str, object]) -> None:
    timing = payload["timing"]
    assert isinstance(timing, dict)
    for key in ("total_ms", "subprocess_ms", "zip_ms", "queue_wait_ms"):
        value = timing[key]
        assert isinstance(value, int)
        assert value >= 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("skill_name", "task_type", "payload", "placeholder"),
    [
        (
            "training_notice",
            "training_notice",
            {"training_title": "Safety 101"},
            "【TRAINING_TITLE】",
        ),
        (
            "inspection_record",
            "inspection_record",
            {"inspection_subject": "Site A"},
            "【INSPECTION_SUBJECT】",
        ),
    ],
)
async def test_api_new_skills_success(
    skill_name: str,
    task_type: str,
    payload: dict[str, object],
    placeholder: str,
) -> None:
    task_bytes = json.dumps({"task_type": task_type, "payload": payload}).encode("utf-8")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/run",
            files={
                "template": (
                    "template.docx",
                    _build_docx_bytes(placeholder),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
                "task": ("task.json", task_bytes, "application/json"),
            },
            data={"skill": skill_name},
        )

    assert response.status_code == 200
    assert response.headers["X-Docops-Exit-Code"] == "0"
    request_id = response.headers["X-Docops-Request-Id"]

    zipped = _zip_map(response.content)
    api_result = json.loads(zipped["api_result.json"].decode("utf-8"))
    assert api_result["request_id"] == request_id
    _assert_timing(api_result)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("skill_name", "task_type", "placeholder", "expected_missing"),
    [
        ("training_notice", "training_notice", "【TRAINING_TITLE】", "TRAINING_TITLE"),
        (
            "inspection_record",
            "inspection_record",
            "【INSPECTION_SUBJECT】",
            "INSPECTION_SUBJECT",
        ),
    ],
)
async def test_api_new_skills_missing_required_returns_exit_2(
    skill_name: str,
    task_type: str,
    placeholder: str,
    expected_missing: str,
) -> None:
    task_bytes = json.dumps({"task_type": task_type, "payload": {}}).encode("utf-8")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/run",
            files={
                "template": (
                    "template.docx",
                    _build_docx_bytes(placeholder),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
                "task": ("task.json", task_bytes, "application/json"),
            },
            data={"skill": skill_name},
        )

    assert response.status_code == 200
    assert response.headers["X-Docops-Exit-Code"] == "2"
    request_id = response.headers["X-Docops-Request-Id"]

    zipped = _zip_map(response.content)
    api_result = json.loads(zipped["api_result.json"].decode("utf-8"))
    assert api_result["request_id"] == request_id
    missing = json.loads(zipped["out.missing_fields.json"].decode("utf-8"))
    assert expected_missing in missing["missing_required"]

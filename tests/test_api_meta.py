from __future__ import annotations

import httpx
import pytest

from apps.api.main import app


@pytest.mark.anyio
async def test_meta_returns_supported_capabilities_and_request_id() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/meta")

    assert response.status_code == 200
    request_id = response.headers["X-Docops-Request-Id"]
    assert request_id

    payload = response.json()
    assert payload["version"]
    assert {"meeting_notice", "training_notice", "inspection_record"}.issubset(
        set(payload["supported_skills"])
    )
    assert set(payload["supported_task_types"]) == set(payload["supported_skills"])
    assert set(payload["supported_presets"]) == {"quick", "template", "strict"}

    schemas = payload["task_payload_schemas"]
    assert "meeting_notice" in schemas
    assert "training_notice" in schemas
    assert "inspection_record" in schemas

    meeting_schema = schemas["meeting_notice"]
    assert meeting_schema["extra_policy"] == "forbid"
    assert "fields" in meeting_schema
    assert "meeting_title" in meeting_schema["fields"]

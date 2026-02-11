from __future__ import annotations

import httpx
import pytest

from apps.api.main import app


@pytest.mark.anyio
async def test_web_console_returns_html_and_request_id_header() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/web")

    assert response.status_code == 200
    assert response.headers["X-Docops-Request-Id"]
    body = response.text
    assert "DocOps Web Console" in body
    assert "/v1/meta" in body
    assert "/v1/run" in body
    assert "template" in body
    assert "task" in body
    assert "strict" in body

from __future__ import annotations

import httpx
import pytest

from apps.api.main import app


@pytest.mark.anyio
async def test_request_id_header_present_for_404() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/__does_not_exist__")

    assert response.status_code == 404
    assert response.headers["X-Docops-Request-Id"]


@pytest.mark.anyio
async def test_request_id_header_present_for_405() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/healthz")

    assert response.status_code == 405
    assert response.headers["X-Docops-Request-Id"]

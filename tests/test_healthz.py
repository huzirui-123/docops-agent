from __future__ import annotations

import httpx
import pytest

from apps.api.main import app


@pytest.mark.anyio
async def test_health_returns_ok_and_request_id() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["X-Docops-Request-Id"]

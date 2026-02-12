from __future__ import annotations

import base64

import httpx
import pytest

from apps.api.main import app


@pytest.mark.anyio
async def test_web_console_disabled_returns_404_with_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCOPS_ENABLE_WEB_CONSOLE", "0")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/web")

    assert response.status_code == 404
    request_id = response.headers["X-Docops-Request-Id"]
    payload = response.json()
    assert payload["error_code"] == "NOT_FOUND"
    assert payload["detail"]["request_id"] == request_id


@pytest.mark.anyio
async def test_meta_disabled_returns_404_with_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCOPS_ENABLE_META", "0")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/meta")

    assert response.status_code == 404
    request_id = response.headers["X-Docops-Request-Id"]
    payload = response.json()
    assert payload["error_code"] == "NOT_FOUND"
    assert payload["detail"]["request_id"] == request_id


@pytest.mark.anyio
async def test_web_console_requires_basic_auth_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCOPS_ENABLE_WEB_CONSOLE", "1")
    monkeypatch.setenv("DOCOPS_WEB_BASIC_AUTH", "u:p")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/web")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="docops"'
    request_id = response.headers["X-Docops-Request-Id"]
    payload = response.json()
    assert payload["error_code"] == "UNAUTHORIZED"
    assert payload["detail"]["request_id"] == request_id


@pytest.mark.anyio
async def test_meta_requires_basic_auth_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCOPS_WEB_BASIC_AUTH", "u:p")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/meta")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="docops"'
    request_id = response.headers["X-Docops-Request-Id"]
    payload = response.json()
    assert payload["error_code"] == "UNAUTHORIZED"
    assert payload["detail"]["request_id"] == request_id


@pytest.mark.anyio
async def test_web_console_accepts_valid_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCOPS_ENABLE_WEB_CONSOLE", "1")
    monkeypatch.setenv("DOCOPS_WEB_BASIC_AUTH", "u:p")
    token = base64.b64encode(b"u:p").decode("ascii")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/web", headers={"Authorization": f"Basic {token}"})

    assert response.status_code == 200
    assert "DocOps Web Console" in response.text
    assert response.headers["X-Docops-Request-Id"]


@pytest.mark.anyio
async def test_meta_accepts_valid_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCOPS_WEB_BASIC_AUTH", "u:p")
    token = base64.b64encode(b"u:p").decode("ascii")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/meta", headers={"Authorization": f"Basic {token}"})

    assert response.status_code == 200
    assert response.headers["X-Docops-Request-Id"]
    payload = response.json()
    assert "supported_skills" in payload

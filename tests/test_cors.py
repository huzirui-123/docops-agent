from __future__ import annotations

import importlib
from collections.abc import Generator

import httpx
import pytest

import apps.api.main as api_main

_CORS_ENV_KEYS = (
    "DOCOPS_ENABLE_CORS",
    "DOCOPS_CORS_ALLOW_ORIGINS",
    "DOCOPS_CORS_ALLOW_CREDENTIALS",
    "DOCOPS_CORS_MAX_AGE",
)


def _reload_api_app() -> httpx.ASGITransport:
    module = importlib.reload(api_main)
    return httpx.ASGITransport(app=module.app)


@pytest.fixture(autouse=True)
def _cleanup_cors_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    for key in _CORS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("DOCOPS_WEB_BASIC_AUTH", raising=False)
    monkeypatch.setenv("DOCOPS_ENABLE_META", "1")
    yield
    for key in _CORS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("DOCOPS_WEB_BASIC_AUTH", raising=False)
    monkeypatch.setenv("DOCOPS_ENABLE_META", "1")
    importlib.reload(api_main)


@pytest.mark.anyio
async def test_cors_disabled_by_default_keeps_request_id_header() -> None:
    transport = _reload_api_app()
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/meta", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert response.headers["X-Docops-Request-Id"]


@pytest.mark.anyio
async def test_cors_enabled_adds_origin_and_exposed_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = "http://localhost:5173"
    monkeypatch.setenv("DOCOPS_ENABLE_CORS", "1")
    monkeypatch.setenv("DOCOPS_CORS_ALLOW_ORIGINS", origin)

    transport = _reload_api_app()
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/meta", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    exposed = response.headers.get("access-control-expose-headers", "")
    assert "x-docops-request-id" in exposed.lower()
    assert response.headers["X-Docops-Request-Id"]


@pytest.mark.anyio
async def test_cors_preflight_on_run_returns_cors_headers_and_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = "http://localhost:5173"
    monkeypatch.setenv("DOCOPS_ENABLE_CORS", "1")
    monkeypatch.setenv("DOCOPS_CORS_ALLOW_ORIGINS", origin)

    transport = _reload_api_app()
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/v1/run",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code in {200, 204}
    assert response.headers.get("access-control-allow-origin") == origin
    assert "access-control-allow-methods" in response.headers
    assert response.headers["X-Docops-Request-Id"]

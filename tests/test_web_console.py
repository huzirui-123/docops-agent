from __future__ import annotations

import httpx
import pytest

from apps.api.main import app


@pytest.mark.anyio
async def test_web_console_default_disabled_returns_not_found() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/web")
        static_response = await client.get("/web/static/web_console.js")

    assert response.status_code == 404
    assert response.headers["X-Docops-Request-Id"]
    assert static_response.status_code == 404
    assert static_response.headers["X-Docops-Request-Id"]


@pytest.mark.anyio
async def test_web_console_returns_html_and_request_id_header_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCOPS_ENABLE_WEB_CONSOLE", "1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/web")
        js_response = await client.get("/web/static/web_console.js")
        css_response = await client.get("/web/static/web_console.css")

    assert response.status_code == 200
    assert response.headers["X-Docops-Request-Id"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "no-store" in response.headers["Cache-Control"]
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp

    body = response.text
    assert "DocOps Web Console" in body
    assert "/v1/meta" in body
    assert "/v1/run" in body
    assert "API Base URL" in body
    assert "Load Meta" in body
    assert "Run" in body
    assert "Request ID" in body
    assert "Download ZIP" in body
    assert "/web/static/web_console.js" in body
    assert "/web/static/web_console.css" in body

    assert js_response.status_code == 200
    assert js_response.headers["X-Docops-Request-Id"]
    assert js_response.headers["Content-Type"].startswith("application/javascript")
    assert js_response.headers["X-Content-Type-Options"] == "nosniff"
    assert js_response.headers["Referrer-Policy"] == "no-referrer"
    assert "no-store" in js_response.headers["Cache-Control"]
    js_csp = js_response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in js_csp
    assert "script-src 'self'" in js_csp
    assert "frame-ancestors 'none'" in js_csp
    assert "DocOps Web Console JS" in js_response.text

    assert css_response.status_code == 200
    assert css_response.headers["X-Docops-Request-Id"]
    assert css_response.headers["Content-Type"].startswith("text/css")

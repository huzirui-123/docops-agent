from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.requests import Request

from apps.api.main import _register_cleanup_path, request_id_middleware


def _build_request(path: str) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


@pytest.mark.anyio
async def test_middleware_cleans_registered_paths_on_exception(tmp_path: Path) -> None:
    request = _build_request("/boom")
    to_cleanup = tmp_path / "registered"
    to_cleanup.mkdir(parents=True, exist_ok=True)
    (to_cleanup / "marker.txt").write_text("x", encoding="utf-8")

    async def call_next(_request: Request):
        _register_cleanup_path(_request, to_cleanup)
        raise RuntimeError("boom")

    response = await request_id_middleware(request, call_next)

    assert response.status_code == 500
    request_id = response.headers.get("X-Docops-Request-Id")
    assert request_id

    payload = json.loads(response.body.decode("utf-8"))
    assert payload["error_code"] == "INTERNAL_ERROR"
    assert payload["detail"]["request_id"] == request_id
    assert not to_cleanup.exists()

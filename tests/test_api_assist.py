from __future__ import annotations

import httpx
import pytest

from apps.api import main


@pytest.mark.anyio
async def test_assist_returns_suggestion_and_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCOPS_ENABLE_ASSIST", "1")

    def _fake_ollama(*, prompt: str) -> dict[str, object]:
        assert "用户问题" in prompt
        return {
            "model": "qwen3:8b",
            "response": "1. 明确会议主题\n2. 明确时间地点\n3. 增加参会对象",
            "eval_count": 100,
            "prompt_eval_count": 42,
        }

    monkeypatch.setattr(main, "_call_ollama_generate", _fake_ollama)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/assist",
            json={
                "prompt": "帮我优化这份会议通知",
                "skill": "meeting_notice",
                "task": {
                    "task_type": "meeting_notice",
                    "payload": {"meeting_title": "周例会"},
                },
            },
        )

    assert response.status_code == 200
    assert response.headers["X-Docops-Request-Id"]
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model"] == "qwen3:8b"
    assert "会议" in payload["answer"]
    assert payload["usage"]["eval_count"] == 100


@pytest.mark.anyio
async def test_assist_rejects_empty_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCOPS_ENABLE_ASSIST", "1")

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/v1/assist", json={"prompt": "  "})

    assert response.status_code == 400
    assert response.headers["X-Docops-Request-Id"]
    payload = response.json()
    assert payload["error_code"] == "INVALID_ARGUMENT"
    assert payload["detail"]["field"] == "prompt"


@pytest.mark.anyio
async def test_assist_rejects_skill_task_type_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCOPS_ENABLE_ASSIST", "1")

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/v1/assist",
            json={
                "prompt": "帮我优化这份通知",
                "skill": "meeting_notice",
                "task": {"task_type": "training_notice", "payload": {}},
            },
        )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "INVALID_ARGUMENT_CONFLICT"
    assert payload["detail"]["request_id"] == response.headers["X-Docops-Request-Id"]


@pytest.mark.anyio
async def test_assist_returns_404_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCOPS_ENABLE_ASSIST", "0")

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/v1/assist", json={"prompt": "你好"})

    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == "NOT_FOUND"


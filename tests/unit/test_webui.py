from aishelf.webui import config


def test_get_settings_defaults(monkeypatch):
    for var in ("HERMES_BASE_URL", "HERMES_API_KEY", "HERMES_MODEL"):
        monkeypatch.delenv(var, raising=False)
    s = config.get_settings()
    assert s["base_url"] == "http://127.0.0.1:8642/v1"
    assert s["model"] == "hermes-agent"
    assert s["api_key"]  # non-empty default


def test_get_settings_env_override(monkeypatch):
    monkeypatch.setenv("HERMES_BASE_URL", "http://example/v1")
    monkeypatch.setenv("HERMES_API_KEY", "k")
    monkeypatch.setenv("HERMES_MODEL", "m")
    s = config.get_settings()
    assert s == {"base_url": "http://example/v1", "api_key": "k", "model": "m"}


import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIStatusError

from aishelf.webui import app as webui_app


def _chunk(content):
    """Fake an OpenAI streaming chunk with one choice delta."""
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice])


class _FakeCompletions:
    def __init__(self, chunks=None, exc=None):
        self._chunks = chunks or []
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return iter(self._chunks)


class _FakeClient:
    def __init__(self, chunks=None, exc=None):
        self.chat = SimpleNamespace(completions=_FakeCompletions(chunks, exc))


def _events(resp):
    """Parse an SSE response body into a list of decoded JSON payloads."""
    out = []
    for block in resp.text.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            out.append(json.loads(block[len("data: "):]))
    return out


def _post(client, **kwargs):
    return client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}, **kwargs)


def test_chat_streams_deltas(monkeypatch):
    fake = _FakeClient(chunks=[_chunk("Hello"), _chunk(" world"), _chunk(None)])
    monkeypatch.setattr(webui_app, "get_client", lambda: fake)
    client = TestClient(webui_app.app)
    resp = _post(client)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _events(resp)
    assert {"delta": "Hello"} in events
    assert {"delta": " world"} in events
    assert {"done": True} in events
    # the None-content chunk must NOT produce a delta event
    assert {"delta": None} not in events


def test_chat_connection_error(monkeypatch):
    exc = APIConnectionError(request=httpx.Request("POST", "http://localhost"))
    monkeypatch.setattr(webui_app, "get_client", lambda: _FakeClient(exc=exc))
    client = TestClient(webui_app.app)
    resp = _post(client)
    assert resp.status_code == 200
    events = _events(resp)
    assert any("error" in e for e in events)


def test_chat_empty_messages(monkeypatch):
    monkeypatch.setattr(webui_app, "get_client", lambda: _FakeClient())
    client = TestClient(webui_app.app)
    resp = client.post("/api/chat", json={"messages": []})
    assert resp.status_code == 400


def test_index_served():
    client = TestClient(webui_app.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]

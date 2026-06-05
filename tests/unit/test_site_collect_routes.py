import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    from aishelf.site.app import app
    return TestClient(app)


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks

    class _C:
        def __init__(self, chunks):
            self._chunks = chunks

        def create(self, **kwargs):
            return iter(self._chunks)

    @property
    def chat(self):
        return SimpleNamespace(completions=self._C(self._chunks))


def test_collect_page_renders(client):
    r = client.get("/collect")
    assert r.status_code == 200
    assert "采集" in r.text


def test_nav_has_collect_link(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/collect"' in r.text


def test_collect_chat_streams(client, monkeypatch):
    from aishelf.site import hermes
    monkeypatch.setattr(hermes, "get_client", lambda: _FakeClient([_chunk("done writing")]))
    r = client.post("/collect/chat", json={"messages": [{"role": "user", "content": "爬视频"}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "done writing" in r.text


def test_collect_chat_empty_messages_400(client):
    r = client.post("/collect/chat", json={"messages": []})
    assert r.status_code == 400

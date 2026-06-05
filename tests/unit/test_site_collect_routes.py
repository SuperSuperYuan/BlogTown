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
        self.captured = {}
        parent = self

        class _Completions:
            def create(self, **kwargs):
                parent.captured = kwargs
                return iter(parent._chunks)

        self.chat = SimpleNamespace(completions=_Completions())


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


def test_collect_chat_prepends_system_instruction(client, monkeypatch, tmp_path):
    from aishelf.site import hermes
    fake = _FakeClient([_chunk("ok")])
    monkeypatch.setattr(hermes, "get_client", lambda: fake)
    r = client.post("/collect/chat", json={"messages": [{"role": "user", "content": "爬视频"}]})
    assert r.status_code == 200
    sent = fake.captured["messages"]
    # the collection instruction is prepended as a system message...
    assert sent[0]["role"] == "system"
    assert str(tmp_path.resolve()) in sent[0]["content"]  # carries the absolute data dir
    # ...and the user's message is forwarded after it
    assert sent[-1] == {"role": "user", "content": "爬视频"}


def test_collect_chat_empty_messages_400(client):
    r = client.post("/collect/chat", json={"messages": []})
    assert r.status_code == 400

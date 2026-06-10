import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


TOKEN = "test-token"
AUTH = {"X-Collect-Token": TOKEN}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    allow = tmp_path / "allow.txt"
    allow.write_text(f"{TOKEN}\n", encoding="utf-8")
    monkeypatch.setenv("AISHELF_COLLECT_ALLOWLIST", str(allow))
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
    assert "Hermes" in r.text


def test_collect_page_has_history_controls(client):
    r = client.get("/collect")
    assert r.status_code == 200
    # chat history persists in the browser and a manual clear button exists
    assert "localStorage" in r.text
    assert "清除对话" in r.text


def test_collect_page_has_progress_indicator(client):
    r = client.get("/collect")
    assert r.status_code == 200
    # in-progress affordances: typing dots before first token, caret while streaming
    assert "showTyping" in r.text
    assert "streaming" in r.text


def test_collect_page_has_token_field(client):
    r = client.get("/collect")
    assert r.status_code == 200
    # a passcode field, persisted in localStorage and sent as the gate header
    assert "collecttoken" in r.text
    assert "aishelf_collect_token" in r.text
    assert "X-Collect-Token" in r.text


def test_nav_has_collect_link(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/collect"' in r.text


def test_collect_chat_streams(client, monkeypatch):
    from aishelf.site import hermes
    monkeypatch.setattr(hermes, "get_client", lambda: _FakeClient([_chunk("done writing")]))
    r = client.post("/collect/chat", json={"messages": [{"role": "user", "content": "爬视频"}]}, headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "done writing" in r.text


def test_collect_chat_prepends_system_instruction(client, monkeypatch, tmp_path):
    from aishelf.site import hermes
    fake = _FakeClient([_chunk("ok")])
    monkeypatch.setattr(hermes, "get_client", lambda: fake)
    r = client.post("/collect/chat", json={"messages": [{"role": "user", "content": "爬视频"}]}, headers=AUTH)
    assert r.status_code == 200
    sent = fake.captured["messages"]
    # the collection instruction is prepended as a system message...
    assert sent[0]["role"] == "system"
    assert str(tmp_path.resolve()) in sent[0]["content"]  # carries the absolute data dir
    # ...and the user's message is forwarded after it
    assert sent[-1] == {"role": "user", "content": "爬视频"}


def test_collect_chat_empty_messages_400(client):
    r = client.post("/collect/chat", json={"messages": []}, headers=AUTH)
    assert r.status_code == 400


def test_collect_chat_no_token_is_403(client, monkeypatch):
    # the allowlist gate must block before Hermes is touched
    from aishelf.site import hermes
    monkeypatch.setattr(hermes, "get_client", lambda: pytest.fail("Hermes must not be called when unauthorized"))
    r = client.post("/collect/chat", json={"messages": [{"role": "user", "content": "爬视频"}]})
    assert r.status_code == 403


def test_collect_chat_bad_token_is_403(client, monkeypatch):
    from aishelf.site import hermes
    monkeypatch.setattr(hermes, "get_client", lambda: pytest.fail("Hermes must not be called when unauthorized"))
    r = client.post(
        "/collect/chat",
        json={"messages": [{"role": "user", "content": "爬视频"}]},
        headers={"X-Collect-Token": "wrong"},
    )
    assert r.status_code == 403


def test_collect_chat_denied_when_allowlist_missing(monkeypatch, tmp_path):
    # fail-closed: no allowlist file -> even a token is rejected
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_COLLECT_ALLOWLIST", str(tmp_path / "does-not-exist.txt"))
    from aishelf.site.app import app
    c = TestClient(app)
    r = c.post(
        "/collect/chat",
        json={"messages": [{"role": "user", "content": "爬视频"}]},
        headers={"X-Collect-Token": "anything"},
    )
    assert r.status_code == 403


def test_collect_chat_triggers_db_sync(client, monkeypatch):
    import threading

    from aishelf.site import hermes
    from aishelf.db import sync as db_sync

    monkeypatch.setattr(hermes, "get_client", lambda: _FakeClient([_chunk("written")]))

    done = threading.Event()
    monkeypatch.setattr(db_sync, "sync", lambda data_dir, db_path: done.set())

    r = client.post(
        "/collect/chat",
        json={"messages": [{"role": "user", "content": "爬视频"}]},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert "written" in r.text  # stream fully consumed
    assert done.wait(timeout=5)  # background sync ran after the stream


def test_collect_page_prefills_q(client):
    r = client.get("/collect", params={"q": "量子计算 视频"})
    assert r.status_code == 200
    assert "量子计算 视频" in r.text  # pre-filled into the composer textarea


def test_collect_page_no_q_is_blank(client):
    r = client.get("/collect")
    assert r.status_code == 200
    # composer renders with no prefilled text between the textarea tags
    assert 'placeholder="输入采集需求，Enter 发送，Shift+Enter 换行…"></textarea>' in r.text

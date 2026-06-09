import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def _write(data_dir, sub, item_id, title, summary="摘要"):
    rec = {
        "id": item_id, "type": "video" if sub == "videos" else "blog",
        "title": title, "author": "作者甲",
        "platform": "youtube" if sub == "videos" else "blog",
        "source_url": f"https://x/{item_id}", "published_at": "2024-01-01",
        "summary": summary, "keywords": [], "collected_at": "2024-01-02T00:00:00",
    }
    if sub == "videos":
        rec["thumbnail_url"] = "https://img/x.jpg"
    d = data_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    _write(tmp_path, "videos", "v1", "大语言模型与检索增强")
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")
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


def test_ask_page_renders(client):
    r = client.get("/ask")
    assert r.status_code == 200
    assert "/ask/chat" in r.text
    assert "renderSources" in r.text


def test_nav_has_ask_link(client):
    r = client.get("/")
    assert 'href="/ask"' in r.text


def test_ask_chat_streams_answer_and_sources(client, monkeypatch):
    from aishelf.site import llm
    monkeypatch.setattr(llm, "OpenAI", lambda **k: _FakeClient([_chunk("检索增强是…")]))
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "什么是检索增强"}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "检索增强是…" in r.text     # streamed answer
    assert '"sources"' in r.text       # a sources event was emitted
    assert "v1" in r.text              # the retrieved item id is in the sources payload


def test_ask_chat_grounds_prompt_on_retrieved_sources(client, monkeypatch):
    from aishelf.site import llm
    fake = _FakeClient([_chunk("ok")])
    monkeypatch.setattr(llm, "OpenAI", lambda **k: fake)
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "检索"}]})
    assert r.status_code == 200
    sent = fake.captured["messages"]
    assert sent[0]["role"] == "system"
    assert "大语言模型与检索增强" in sent[0]["content"]  # retrieved source is in the grounded prompt
    assert sent[-1] == {"role": "user", "content": "检索"}


def test_ask_chat_empty_messages_400(client):
    r = client.post("/ask/chat", json={"messages": []})
    assert r.status_code == 400


def test_ask_chat_is_ungated(client, monkeypatch):
    # no X-Collect-Token header is needed; the LLM is reached
    from aishelf.site import llm
    monkeypatch.setattr(llm, "OpenAI", lambda **k: _FakeClient([_chunk("ans")]))
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert "ans" in r.text

import json

import pytest
from fastapi.testclient import TestClient

from aishelf.site import hermes, llm


def _write(data_dir, sub, item_id, title):
    rec = {
        "id": item_id, "type": "video" if sub == "videos" else "blog",
        "title": title, "author": "作者甲",
        "platform": "youtube" if sub == "videos" else "blog",
        "source_url": f"https://x/{item_id}", "published_at": "2024-01-01",
        "summary": "摘要", "keywords": [], "collected_at": "2024-01-02T00:00:00",
    }
    if sub == "videos":
        rec["thumbnail_url"] = "https://img/x.jpg"
    d = data_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _fake_stream(messages):
    yield hermes.sse({"delta": "碰撞结果"})
    yield hermes.sse({"done": True})


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    _write(tmp_path, "videos", "v1", "视频标题")
    _write(tmp_path, "blogs", "b1", "博客标题")
    from aishelf import embed, alias
    monkeypatch.setattr(embed, "model_name", lambda: None)       # no embeddings -> random_pair path
    monkeypatch.setattr(alias, "is_configured", lambda: False)
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")
    monkeypatch.setattr(llm, "stream_completion", _fake_stream)  # no real LLM call
    from aishelf.site.app import app
    return TestClient(app)


def test_collide_chat_emits_pair_then_delta(client):
    r = client.post("/collide/chat", json={})
    assert r.status_code == 200
    evs = _events(r.text)
    assert "pair" in evs[0]
    assert set(evs[0]["pair"]) == {"a", "b"}
    assert {evs[0]["pair"]["a"]["id"], evs[0]["pair"]["b"]["id"]} == {"v1", "b1"}
    assert any(e.get("delta") == "碰撞结果" for e in evs)


def test_collide_chat_honors_explicit_ids(client):
    r = client.post("/collide/chat", json={"a_id": "v1", "b_id": "b1"})
    evs = _events(r.text)
    assert {evs[0]["pair"]["a"]["id"], evs[0]["pair"]["b"]["id"]} == {"v1", "b1"}


def test_collide_chat_honors_lock_id(client):
    r = client.post("/collide/chat", json={"lock_id": "v1"})
    evs = _events(r.text)
    assert "v1" in {evs[0]["pair"]["a"]["id"], evs[0]["pair"]["b"]["id"]}


def test_collide_chat_empty_library(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    from aishelf import embed, alias
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(alias, "is_configured", lambda: False)
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")   # no items
    from aishelf.site.app import app
    client = TestClient(app)
    evs = _events(client.post("/collide/chat", json={}).text)
    assert any("先去采集" in (e.get("error") or "") for e in evs)

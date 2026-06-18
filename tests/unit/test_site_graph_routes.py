import json

import pytest
from fastapi.testclient import TestClient
from aishelf.site import hermes, llm


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    (tmp_path / "videos").mkdir(parents=True)
    rec = {"id": "v1", "type": "video", "title": "大模型", "author": "作者甲",
           "platform": "youtube", "source_url": "https://x/v1", "published_at": "2024-01-01",
           "summary": "摘要", "keywords": [], "collected_at": "2024-01-02T00:00:00",
           "thumbnail_url": "https://img/x.jpg"}
    (tmp_path / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")     # no ATLAS_EMBED_* -> nodes, no edges
    from aishelf.site.app import app
    return TestClient(app)


def test_api_graph_shape(client):
    r = client.get("/api/graph")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"nodes", "edges", "clusters"}
    assert any(n["id"] == "v1" and n["type"] == "video" and "degree" in n for n in body["nodes"])
    assert body["edges"] == []     # no embeddings configured in tests -> no edges
    assert body["clusters"] == []  # no embeddings -> no clusters


def test_graph_page_renders(client):
    r = client.get("/graph")
    assert r.status_code == 200
    assert "/api/graph" in r.text
    assert "three@0.128" in r.text          # Three.js CDN pin
    assert 'id="globe"' in r.text           # the WebGL container
    assert "OrbitControls" in r.text        # rotate/zoom controls


def test_nav_has_graph_link(client):
    r = client.get("/")
    assert 'href="/graph"' in r.text


def test_api_graph_payload_has_clusters_list(client):
    body = client.get("/api/graph").json()
    assert "clusters" in body and isinstance(body["clusters"], list)


def _events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _fake_path_stream(messages):
    yield hermes.sse({"delta": "因为它们都讲上下文"})
    yield hermes.sse({"done": True})


@pytest.fixture
def path_client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    for sub, vid, title in [("videos", "v1", "提示工程"), ("blogs", "b1", "多智能体")]:
        d = tmp_path / sub
        d.mkdir(parents=True, exist_ok=True)
        rec = {"id": vid, "type": "video" if sub == "videos" else "blog",
               "title": title, "author": "作者甲",
               "platform": "youtube" if sub == "videos" else "blog",
               "source_url": f"https://x/{vid}", "published_at": "2024-01-01",
               "summary": "摘要", "keywords": [], "collected_at": "2024-01-02T00:00:00"}
        if sub == "videos":
            rec["thumbnail_url"] = "https://img/x.jpg"
        (d / f"{vid}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    from aishelf import embed, alias
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(alias, "is_configured", lambda: False)
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")
    monkeypatch.setattr(llm, "stream_completion", _fake_path_stream)
    from aishelf.site.app import app
    return TestClient(app)


def test_graph_path_streams_explanation(path_client):
    r = path_client.post("/graph/path", json={"ids": ["v1", "b1"]})
    assert r.status_code == 200
    evs = _events(r.text)
    assert any(e.get("delta") for e in evs)


def test_graph_path_rejects_single_id(path_client):
    r = path_client.post("/graph/path", json={"ids": ["v1"]})
    assert r.status_code == 400


def test_graph_path_missing_items_emits_error(path_client):
    r = path_client.post("/graph/path", json={"ids": ["ghost1", "ghost2"]})
    assert r.status_code == 200
    evs = _events(r.text)
    assert any("error" in e for e in evs)

import json

import pytest
from fastapi.testclient import TestClient


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
    assert set(body.keys()) == {"nodes", "edges"}
    assert any(n["id"] == "v1" and n["type"] == "video" and "degree" in n for n in body["nodes"])
    assert body["edges"] == []     # no embeddings configured in tests -> no edges


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

import json

import pytest
from fastapi.testclient import TestClient


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


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    _write(tmp_path, "videos", "v1", "大语言模型与检索增强")
    _write(tmp_path, "blogs", "b1", "短视频推荐系统")
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")
    from aishelf.site.app import app
    return TestClient(app)


def test_api_search_cjk(client):
    r = client.get("/api/search", params={"q": "检索"})
    assert r.status_code == 200
    body = r.json()
    assert [h["id"] for h in body["results"]] == ["v1"]


def test_api_search_type_filter(client):
    r = client.get("/api/search", params={"q": "视频", "type": "blog"})
    assert [h["id"] for h in r.json()["results"]] == ["b1"]


def test_api_search_empty_query(client):
    r = client.get("/api/search", params={"q": ""})
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_api_search_bad_type_400(client):
    r = client.get("/api/search", params={"q": "x", "type": "podcast"})
    assert r.status_code == 400

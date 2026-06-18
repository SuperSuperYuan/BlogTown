import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    from aishelf.site.app import app
    return TestClient(app)


def test_api_item_returns_detail(client):
    r = client.get("/api/item/youtube-aaa")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "youtube-aaa"
    assert set(["id", "type", "title", "author", "published_at",
                "summary", "keywords", "note_html"]).issubset(body.keys())
    assert isinstance(body["keywords"], list)


def test_api_item_unknown_is_404(client):
    assert client.get("/api/item/nope-zzz").status_code == 404


def test_api_item_unsafe_id_is_404(client):
    assert client.get("/api/item/a..b").status_code == 404


def test_api_item_no_note_is_empty_html(client):
    body = client.get("/api/item/blog-ccc").json()
    assert body["note_html"] == ""


def test_api_item_renders_note_markdown(client):
    client.post("/notes/youtube-aaa", json={"text": "**重点** 段落"})
    body = client.get("/api/item/youtube-aaa").json()
    assert "<strong>" in body["note_html"]

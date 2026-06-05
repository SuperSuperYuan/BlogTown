import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)  # writable copy so notes can be saved alongside
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    from aishelf.site.app import app
    return TestClient(app)


def test_detail_renders_note_textarea(client):
    r = client.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert 'id="note"' in r.text


def test_detail_prefills_existing_note(client):
    client.post("/notes/youtube-aaa", json={"text": "提前写好的笔记"})
    r = client.get("/videos/youtube-aaa")
    assert "提前写好的笔记" in r.text


def test_save_note_persists(client):
    r = client.post("/notes/youtube-aaa", json={"text": "我的观后感"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    r2 = client.get("/videos/youtube-aaa")
    assert "我的观后感" in r2.text


def test_blog_detail_has_note_editor(client):
    r = client.get("/blogs/blog-ccc")
    assert r.status_code == 200
    assert 'id="note"' in r.text


def test_save_note_invalid_id_400(client):
    r = client.post("/notes/a..b", json={"text": "x"})  # ".." rejected by _safe_id
    assert r.status_code == 400

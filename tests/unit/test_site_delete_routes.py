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
    return TestClient(app), data


def test_delete_removes_record_and_note(client):
    c, data = client
    c.post("/notes/youtube-aaa", json={"text": "笔记"})
    assert (data / "notes" / "youtube-aaa.json").exists()
    r = c.post("/delete/youtube-aaa")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert not (data / "videos" / "youtube-aaa.json").exists()
    assert not (data / "notes" / "youtube-aaa.json").exists()
    assert c.get("/videos/youtube-aaa").status_code == 404


def test_delete_unknown_404(client):
    c, _ = client
    assert c.post("/delete/nope-zzz").status_code == 404


def test_delete_bad_id_400(client):
    c, _ = client
    assert c.post("/delete/a..b").status_code == 400


def test_detail_has_delete_button(client):
    c, _ = client
    r = c.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert 'id="delete-item"' in r.text and "删除" in r.text

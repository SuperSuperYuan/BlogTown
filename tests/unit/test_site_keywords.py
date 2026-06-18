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


def test_keyword_page_lists_matching_items(client):
    r = client.get("/keyword/ai")
    assert r.status_code == 200
    assert "标签" in r.text
    assert "youtube-aaa" in r.text


def test_keyword_page_is_cross_type(client):
    r = client.get("/keyword/research")
    assert r.status_code == 200
    assert "blog-ccc" in r.text


def test_keyword_page_unknown_is_404(client):
    assert client.get("/keyword/zzz-nope").status_code == 404

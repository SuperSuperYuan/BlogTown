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


def test_keywords_index_renders_cloud(client):
    r = client.get("/keywords")
    assert r.status_code == 200
    assert "关键词宇宙" in r.text
    assert "ai" in r.text
    assert "/keyword/ai" in r.text


def test_topbar_has_keywords_link(client):
    r = client.get("/keywords")
    assert 'href="/keywords"' in r.text


def test_keyword_page_shows_cotags(client):
    # blog-ccc carries both "llm" and "research" -> they co-occur
    r = client.get("/keyword/llm")
    assert r.status_code == 200
    assert "常一起出现" in r.text
    assert "/keyword/research" in r.text


def test_keyword_page_no_cotags_for_singleton(client):
    # "agents" only on blog-ddd, alone -> no co-occurrence row
    r = client.get("/keyword/agents")
    assert r.status_code == 200
    assert "常一起出现" not in r.text

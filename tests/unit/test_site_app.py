from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(FIXTURES))
    from aishelf.site.app import app
    return TestClient(app)


def test_home_lists_latest(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "March talk" in r.text       # a video
    assert "May post" in r.text         # a blog


def test_videos_section(client):
    r = client.get("/videos")
    assert r.status_code == 200
    assert "March talk" in r.text and "January talk" in r.text


def test_blogs_section(client):
    r = client.get("/blogs")
    assert r.status_code == 200
    assert "May post" in r.text and "February post" in r.text


def test_video_detail(client):
    r = client.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert "March talk" in r.text
    assert "去原站观看" in r.text       # no embed_url -> link fallback


def test_blog_detail(client):
    r = client.get("/blogs/blog-ccc")
    assert r.status_code == 200
    assert "February post" in r.text and "Example Blog" in r.text


def test_unknown_id_renders_404(client):
    r = client.get("/videos/does-not-exist")
    assert r.status_code == 404
    assert "404" in r.text


def test_author_page(client):
    r = client.get(f"/authors/{quote('Writer Two')}")
    assert r.status_code == 200
    assert "May post" in r.text


def test_search(client):
    r = client.get("/search", params={"q": "march"})
    assert r.status_code == 200
    assert "March talk" in r.text


def test_keyword_filter(client):
    r = client.get("/videos", params={"keyword": "ai"})
    assert r.status_code == 200
    assert "March talk" in r.text and "January talk" not in r.text


def test_empty_data_dir_shows_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    from aishelf.site.app import app
    c = TestClient(app)
    r = c.get("/videos")
    assert r.status_code == 200
    assert "暂无内容" in r.text

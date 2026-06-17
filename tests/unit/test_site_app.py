import json
import shutil
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


def test_search_groups_videos_and_blogs(client):
    # "summary" appears in every record's summary field -> both modalities match
    r = client.get("/search", params={"q": "summary"})
    assert r.status_code == 200
    assert "视频" in r.text and "博客" in r.text


def test_keyword_links_target_section(client):
    # youtube-aaa has keyword "ai"; the detail page's keyword links into /videos
    r = client.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert "/videos?keyword=ai" in r.text


def test_non_http_url_scheme_is_sanitized(tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    videos.mkdir()
    rec = {
        "id": "evil",
        "type": "video",
        "title": "Evil",
        "author": "A",
        "platform": "x",
        "source_url": "javascript:alert(1)",
        "published_at": "2024-01-01",
        "summary": "s",
        "keywords": [],
        "collected_at": "2024-01-01T00:00:00",
        "thumbnail_url": "javascript:alert(2)",
    }
    (videos / "evil.json").write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    from aishelf.site.app import app
    r = TestClient(app).get("/videos/evil")
    assert r.status_code == 200
    assert "javascript:alert" not in r.text  # both href and img src blanked


def test_safe_url_filter_allows_only_http_https():
    from aishelf.site.app import _safe_url
    assert _safe_url("https://x/y.jpg") == "https://x/y.jpg"
    assert _safe_url("http://x/y") == "http://x/y"
    assert _safe_url("//evil.com/x.js") == ""   # protocol-relative blanked
    assert _safe_url("javascript:alert(1)") == ""
    assert _safe_url("data:text/html;base64,xxx") == ""
    assert _safe_url("evil.com/x") == ""        # scheme-less blanked
    assert _safe_url("") == "" and _safe_url(None) == ""


def test_detail_renders_for_record_with_unsafe_id(tmp_path, monkeypatch):
    # a loaded record whose id is not path-safe must not 500 its own detail page
    videos = tmp_path / "videos"
    videos.mkdir()
    rec = {
        "id": "bad id",  # contains a space -> safe_id would reject
        "type": "video",
        "title": "Bad Id",
        "author": "A",
        "platform": "x",
        "source_url": "https://y/badid",
        "published_at": "2024-01-01",
        "summary": "s",
        "keywords": [],
        "collected_at": "2024-01-01T00:00:00",
        "thumbnail_url": "https://img/badid.jpg",
    }
    (videos / "bad id.json").write_text(json.dumps(rec), encoding="utf-8")
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    from aishelf.site.app import app
    r = TestClient(app).get("/videos/" + quote("bad id"))
    assert r.status_code == 200  # renders with an empty note, not a 500
    assert "Bad Id" in r.text


@pytest.fixture
def rw_client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    monkeypatch.setenv("ATLAS_BLOG_AUTHOR", "我")
    from aishelf.site.app import app
    return TestClient(app)


def test_self_post_appears_in_blogs_list_with_badge(rw_client):
    rw_client.post("/posts", data={"title": "我的原创长文", "body": "正文内容"},
                   follow_redirects=False)
    r = rw_client.get("/blogs")
    assert r.status_code == 200
    assert "我的原创长文" in r.text   # mixed with collected blogs
    assert "原创" in r.text          # badge present
    assert "May post" in r.text       # collected blogs still listed


def test_self_post_is_searchable_after_create(rw_client):
    # creating a post triggers an off-thread sync; force a synchronous sync so
    # the assertion is deterministic in the test (no sleeping on a daemon thread)
    from aishelf.db import sync as db_sync
    from aishelf.db.config import default_db_path
    import os
    data_dir = os.environ["AISHELF_DATA_DIR"]
    rw_client.post("/posts", data={"title": "可检索原创", "body": "独特关键词xyzzy"},
                   follow_redirects=False)
    db_sync.sync(data_dir, default_db_path(data_dir))
    r = rw_client.get("/api/search", params={"q": "可检索原创"})
    assert any("可检索原创" in hit["title"] for hit in r.json()["results"])


def _seed_hook_site(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    rec = {"id": "v1", "type": "video", "title": "大语言模型", "author": "作者甲",
           "platform": "youtube", "source_url": "https://x/v1",
           "published_at": "2024-01-01", "summary": "摘要", "keywords": [],
           "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}
    (tmp_path / "videos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    from aishelf.db.sync import sync
    from aishelf.db import schema
    sync(tmp_path, tmp_path / "atlas.db")
    con = schema.connect(tmp_path / "atlas.db")
    con.execute("UPDATE items SET hook=? WHERE id=?", ("一眼说清为什么值得看", "v1"))
    con.commit()
    con.close()


def test_videos_page_shows_hook(tmp_path, monkeypatch):
    _seed_hook_site(tmp_path, monkeypatch)
    from aishelf.site.app import app
    client = TestClient(app)
    r = client.get("/videos")
    assert r.status_code == 200
    assert "一眼说清为什么值得看" in r.text


def test_videos_page_renders_without_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    rec = {"id": "v1", "type": "video", "title": "无钩子视频", "author": "作者甲",
           "platform": "youtube", "source_url": "https://x/v1",
           "published_at": "2024-01-01", "summary": "摘要", "keywords": [],
           "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}
    (tmp_path / "videos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    from aishelf.site.app import app
    client = TestClient(app)
    r = client.get("/videos")
    assert r.status_code == 200
    assert "无钩子视频" in r.text


import json as _dj
from fastapi.testclient import TestClient as _DClient


def _seed_one_video(tmp_path, vid="v1", title="速读测试视频", collected="2026-06-10T00:00:00"):
    rec = {"id": vid, "type": "video", "title": title, "author": "作者甲",
           "platform": "youtube", "source_url": f"https://x/{vid}",
           "published_at": "2024-01-01", "summary": "摘要", "keywords": [],
           "collected_at": collected, "thumbnail_url": "https://img/x.jpg"}
    (tmp_path / "videos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "videos" / f"{vid}.json").write_text(_dj.dumps(rec, ensure_ascii=False), encoding="utf-8")


def test_home_shows_digest_card_with_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    _seed_one_video(tmp_path)
    from aishelf.db.sync import sync
    from aishelf.db import schema
    sync(tmp_path, tmp_path / "atlas.db")
    con = schema.connect(tmp_path / "atlas.db")
    con.execute("UPDATE items SET hook=? WHERE id=?", ("速读钩子", "v1"))
    con.commit()
    con.close()
    from aishelf.site.app import app
    r = _DClient(app).get("/")
    assert r.status_code == 200
    assert "今日速读" in r.text
    assert "速读测试视频" in r.text
    assert "速读钩子" in r.text


def test_home_digest_absent_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")   # no items
    from aishelf.site.app import app
    r = _DClient(app).get("/")
    assert r.status_code == 200
    assert "今日速读" not in r.text

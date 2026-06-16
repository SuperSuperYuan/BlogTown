import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)  # writable copy so posts can be created
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    monkeypatch.setenv("ATLAS_BLOG_AUTHOR", "我")
    from aishelf.site.app import app
    return TestClient(app)


def test_write_page_renders_empty_form(client):
    r = client.get("/write")
    assert r.status_code == 200
    assert 'name="title"' in r.text and 'name="body"' in r.text


def test_create_post_redirects_to_detail(client):
    r = client.post("/posts", data={"title": "原创文章", "body": "# 标题\n\n内容"},
                     follow_redirects=False)
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/blogs/post-")
    detail = client.get(location)
    assert detail.status_code == 200
    assert "原创" in detail.text
    assert "阅读全文" not in detail.text  # source-site button hidden for self posts


def test_create_post_empty_title_does_not_write(client):
    r = client.post("/posts", data={"title": "  ", "body": "内容"},
                    follow_redirects=False)
    assert r.status_code == 400
    blogs = client.get("/blogs")
    assert "post-" not in blogs.text


def test_write_edit_page_prefills_self_post(client):
    created = client.post("/posts", data={"title": "可编辑", "body": "原始正文"},
                          follow_redirects=False)
    item_id = created.headers["location"].rsplit("/", 1)[-1]
    r = client.get(f"/write/{item_id}")
    assert r.status_code == 200
    assert "可编辑" in r.text and "原始正文" in r.text


def test_write_edit_page_404_for_collected(client):
    r = client.get("/write/blog-ccc")  # a collected fixture blog
    assert r.status_code == 404


def test_update_post_changes_body_and_keeps_published(client):
    import json, os
    created = client.post("/posts", data={"title": "t1", "body": "b1"},
                          follow_redirects=False)
    item_id = created.headers["location"].rsplit("/", 1)[-1]
    blog_path = os.path.join(os.environ["AISHELF_DATA_DIR"], "blogs", f"{item_id}.json")
    before = json.loads(open(blog_path, encoding="utf-8").read())["published_at"]
    r = client.post(f"/posts/{item_id}", data={"title": "t2", "body": "# 改了"},
                    follow_redirects=False)
    assert r.status_code == 303
    after = json.loads(open(blog_path, encoding="utf-8").read())
    assert after["published_at"] == before  # preserved across edit
    assert after["body"] == "# 改了"
    detail = client.get(f"/blogs/{item_id}")
    assert "改了" in detail.text


def test_update_post_404_for_collected(client):
    r = client.post("/posts/blog-ccc", data={"title": "x", "body": "y"},
                    follow_redirects=False)
    assert r.status_code == 404


def test_preview_returns_sanitized_html(client):
    r = client.post("/posts/preview", json={"body": "# 预览\n\n<script>x</script>"})
    assert r.status_code == 200
    html = r.json()["html"]
    assert "<h1>" in html
    assert "<script" not in html


def test_collected_blog_detail_unchanged(client):
    r = client.get("/blogs/blog-ccc")
    assert r.status_code == 200
    assert "阅读全文" in r.text  # collected items keep the source-site button
    assert "原创" not in r.text


def test_create_post_empty_body_returns_400(client):
    r = client.post("/posts", data={"title": "有标题", "body": "   "},
                    follow_redirects=False)
    assert r.status_code == 400
    assert "标题和正文" in r.text


def test_update_post_empty_title_returns_400(client):
    created = client.post("/posts", data={"title": "t", "body": "b"},
                          follow_redirects=False)
    item_id = created.headers["location"].rsplit("/", 1)[-1]
    r = client.post(f"/posts/{item_id}", data={"title": "  ", "body": "b"},
                    follow_redirects=False)
    assert r.status_code == 400


def test_create_post_error_repopulates_submitted_fields(client):
    r = client.post("/posts", data={"title": "有内容标题", "body": "   "},
                    follow_redirects=False)
    assert r.status_code == 400
    assert "有内容标题" in r.text  # submitted title echoed back into the form

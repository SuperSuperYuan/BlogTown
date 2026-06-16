import json
from pathlib import Path

import pytest

from aishelf.contract.models import BlogItem
from aishelf.site import posts


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_BLOG_AUTHOR", "测试作者")
    return tmp_path


def _read_json(data_dir, item_id):
    return json.loads((data_dir / "blogs" / f"{item_id}.json").read_text(encoding="utf-8"))


def test_create_post_writes_self_blog_record(data_dir):
    item = posts.create_post("我的标题", "# 正文\n\n这是一段内容。")
    assert isinstance(item, BlogItem)
    assert item.id.startswith("post-")
    assert item.origin == "self"
    assert item.type == "blog"
    assert item.author == "测试作者"
    assert item.title == "我的标题"
    assert item.body == "# 正文\n\n这是一段内容。"
    assert item.keywords == []
    assert item.platform == "atlas"
    assert item.source_url == ""
    on_disk = _read_json(data_dir, item.id)
    assert on_disk["origin"] == "self"
    assert on_disk["body"] == "# 正文\n\n这是一段内容。"


def test_summary_is_auto_extracted_from_body(data_dir):
    item = posts.create_post("t", "# 大标题\n\n**重点**内容在这里，更多文字跟随其后。")
    assert "大标题" in item.summary or "重点" in item.summary
    assert "#" not in item.summary and "*" not in item.summary
    assert len(item.summary) <= 120  # SUMMARY_LEN cap


def test_create_post_id_is_path_safe_and_stable_per_clock(data_dir):
    item = posts.create_post("标题", "body", now=lambda: "2026-06-16T12:00:00")
    from aishelf.site.items import safe_id
    assert safe_id(item.id) == item.id


def test_read_post_returns_none_for_missing(data_dir):
    assert posts.read_post("post-does-not-exist") is None


def test_read_post_returns_none_for_collected_record(data_dir):
    blogs = data_dir / "blogs"
    blogs.mkdir(parents=True)
    (blogs / "blog-x.json").write_text(json.dumps({
        "id": "blog-x", "type": "blog", "title": "c", "author": "a",
        "platform": "p", "source_url": "https://e/x", "published_at": "2024-01-01",
        "summary": "s", "keywords": [], "collected_at": "2024-01-02T00:00:00",
    }), encoding="utf-8")
    assert posts.read_post("blog-x") is None  # origin != self


def test_update_post_preserves_published_at_and_updates_fields(data_dir):
    created = posts.create_post("旧标题", "旧正文", now=lambda: "2026-01-01T00:00:00")
    original_published = created.published_at
    updated = posts.update_post(created.id, "新标题", "# 新正文\n\n新的内容")
    assert updated.title == "新标题"
    assert updated.body == "# 新正文\n\n新的内容"
    assert updated.published_at == original_published  # unchanged on edit
    assert "新" in updated.summary


def test_update_post_rejects_unknown_id(data_dir):
    with pytest.raises(LookupError):
        posts.update_post("post-nope", "t", "b")


def test_update_post_rejects_collected_record(data_dir):
    blogs = data_dir / "blogs"
    blogs.mkdir(parents=True)
    (blogs / "blog-y.json").write_text(json.dumps({
        "id": "blog-y", "type": "blog", "title": "c", "author": "a",
        "platform": "p", "source_url": "https://e/y", "published_at": "2024-01-01",
        "summary": "s", "keywords": [], "collected_at": "2024-01-02T00:00:00",
    }), encoding="utf-8")
    with pytest.raises(LookupError):
        posts.update_post("blog-y", "t", "b")

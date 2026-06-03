import pytest
from pydantic import ValidationError

from aishelf.contract.models import BlogItem, VideoItem, parse_item

VIDEO = {
    "id": "youtube-abc",
    "type": "video",
    "title": "A talk",
    "author": "Some Author",
    "platform": "youtube",
    "source_url": "https://youtube.com/watch?v=abc",
    "published_at": "2024-01-02",
    "summary": "a summary",
    "keywords": ["ai", "talk"],
    "collected_at": "2024-01-03T10:00:00",
    "thumbnail_url": "https://img/abc.jpg",
    "duration_seconds": 100,
}

BLOG = {
    "id": "blog-xyz",
    "type": "blog",
    "title": "A post",
    "author": "Some Writer",
    "platform": "example.com",
    "source_url": "https://example.com/x",
    "published_at": "2024-02-01T08:00:00+00:00",
    "summary": "a summary",
    "keywords": [],
    "collected_at": "2024-02-02T10:00:00",
}


def test_parse_video_returns_videoitem():
    item = parse_item(VIDEO)
    assert isinstance(item, VideoItem)
    assert item.type == "video"
    assert item.duration_seconds == 100


def test_parse_blog_returns_blogitem():
    item = parse_item(BLOG)
    assert isinstance(item, BlogItem)
    assert item.type == "blog"
    assert item.keywords == []


def test_video_optional_fields_default_none():
    item = parse_item(BLOG)
    assert item.cover_image_url is None
    assert item.site_name is None


def test_missing_required_field_raises():
    bad = dict(VIDEO)
    del bad["title"]
    with pytest.raises(ValidationError):
        parse_item(bad)


def test_keywords_must_be_list_not_string():
    bad = dict(VIDEO)
    bad["keywords"] = "ai,talk"
    with pytest.raises(ValidationError):
        parse_item(bad)


def test_unknown_fields_ignored():
    extra = dict(VIDEO)
    extra["nonsense"] = 123
    item = parse_item(extra)
    assert not hasattr(item, "nonsense")


def test_unknown_type_raises():
    bad = dict(VIDEO)
    bad["type"] = "podcast"
    with pytest.raises(ValidationError):
        parse_item(bad)

import json
from pathlib import Path

from aishelf.contract.loader import load_items

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


def _write_video(directory, item_id, published_at):
    rec = {
        "id": item_id,
        "type": "video",
        "title": item_id,
        "author": "A",
        "platform": "youtube",
        "source_url": f"https://y/{item_id}",
        "published_at": published_at,
        "summary": "s",
        "keywords": [],
        "collected_at": "2024-01-01T00:00:00",
        "thumbnail_url": f"https://img/{item_id}.jpg",
    }
    (directory / f"{item_id}.json").write_text(json.dumps(rec), encoding="utf-8")


def test_load_items_returns_valid_records_sorted_desc():
    items = load_items(FIXTURES)
    # 4 valid files; broken.json is skipped
    assert len(items) == 4
    # sorted by published_at descending: May, March, Feb, Jan
    assert [it.id for it in items] == [
        "blog-ddd",
        "youtube-aaa",
        "blog-ccc",
        "bilibili-bbb",
    ]


def test_load_items_skips_malformed_without_raising():
    items = load_items(FIXTURES)
    assert all(it.id != "broken" for it in items)


def test_load_items_missing_dir_returns_empty(tmp_path):
    assert load_items(tmp_path) == []


def test_sort_normalizes_timezone_and_handles_unparseable(tmp_path):
    videos = tmp_path / "videos"
    videos.mkdir()
    # tz-aware: 2024-06-01T05:00+09:00 == 2024-05-31T20:00 UTC, which is EARLIER
    # than the naive 2024-06-01T00:00 — even though it sorts later as a string.
    _write_video(videos, "tz-aware", "2024-06-01T05:00:00+09:00")
    _write_video(videos, "naive-later", "2024-06-01T00:00:00")
    # unparseable date must not crash and sorts last (treated as minimum).
    _write_video(videos, "no-date", "sometime last spring")

    items = load_items(tmp_path)
    assert [it.id for it in items] == ["naive-later", "tz-aware", "no-date"]

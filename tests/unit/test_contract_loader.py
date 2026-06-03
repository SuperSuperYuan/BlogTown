from pathlib import Path

from aishelf.contract.loader import load_items

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


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

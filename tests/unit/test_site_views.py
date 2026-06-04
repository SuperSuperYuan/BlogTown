from pathlib import Path

from aishelf.contract.loader import load_items
from aishelf.site import views

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"
ITEMS = load_items(FIXTURES)  # sorted desc: blog-ddd, youtube-aaa, blog-ccc, bilibili-bbb


def _ids(items):
    return [it.id for it in items]


def test_videos_and_blogs_split_preserves_order():
    assert _ids(views.videos(ITEMS)) == ["youtube-aaa", "bilibili-bbb"]
    assert _ids(views.blogs(ITEMS)) == ["blog-ddd", "blog-ccc"]


def test_search_matches_title_summary_and_keyword_case_insensitive():
    assert _ids(views.search(ITEMS, "march")) == ["youtube-aaa"]      # title/summary
    assert _ids(views.search(ITEMS, "MARCH")) == ["youtube-aaa"]      # case-insensitive
    assert _ids(views.search(ITEMS, "agents")) == ["blog-ddd"]        # keyword hit
    assert views.search(ITEMS, "zzz") == []                           # miss
    assert views.search(ITEMS, "") == []                             # empty query


def test_by_keyword_exact_keyword_entry():
    assert _ids(views.by_keyword(ITEMS, "ai")) == ["youtube-aaa"]
    assert _ids(views.by_keyword(ITEMS, "research")) == ["blog-ccc"]
    assert views.by_keyword(ITEMS, "nope") == []


def test_author_key_and_grouping():
    yt = next(it for it in ITEMS if it.id == "youtube-aaa")
    assert views.author_key(yt) == "Author One"  # no author_id -> author name
    assert _ids(views.by_author(ITEMS, "Writer Two")) == ["blog-ddd"]


def test_paginate_pages_and_clamp():
    p1 = views.paginate(ITEMS, page=1, per_page=2)
    assert _ids(p1.items) == ["blog-ddd", "youtube-aaa"]
    assert (p1.total, p1.total_pages, p1.has_prev, p1.has_next) == (4, 2, False, True)

    p2 = views.paginate(ITEMS, page=2, per_page=2)
    assert _ids(p2.items) == ["blog-ccc", "bilibili-bbb"]
    assert (p2.has_prev, p2.has_next) == (True, False)

    clamped = views.paginate(ITEMS, page=99, per_page=2)
    assert clamped.page == 2  # clamped to last page

    empty = views.paginate([], page=1, per_page=2)
    assert empty.items == [] and empty.total == 0 and empty.total_pages == 1

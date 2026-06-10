import json

from aishelf.db import schema
from aishelf.db.search import search
from aishelf.db.sync import sync
from aishelf.db import search as search_mod


def _write(data_dir, sub, item_id, title, summary="摘要", keywords=None):
    rec = {
        "id": item_id,
        "type": "video" if sub == "videos" else "blog",
        "title": title, "author": "作者甲",
        "platform": "youtube" if sub == "videos" else "blog",
        "source_url": f"https://x/{item_id}",
        "published_at": "2024-01-01", "summary": summary,
        "keywords": keywords or [], "collected_at": "2024-01-02T00:00:00",
    }
    if sub == "videos":
        rec["thumbnail_url"] = f"https://img/{item_id}.jpg"
    d = data_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _seed(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1", "大语言模型与检索增强生成 RAG")
    _write(data, "blogs", "b1", "短视频推荐系统")
    sync(data, db)
    return db


def test_search_cjk_two_char(tmp_path):
    db = _seed(tmp_path)
    hits = search(db, "检索")
    assert [h.id for h in hits] == ["v1"]


def test_search_cjk_multichar(tmp_path):
    db = _seed(tmp_path)
    assert [h.id for h in search(db, "大语言模型")] == ["v1"]


def test_search_ascii_case_insensitive(tmp_path):
    db = _seed(tmp_path)
    assert [h.id for h in search(db, "rag")] == ["v1"]


def test_search_type_filter(tmp_path):
    db = _seed(tmp_path)
    assert search(db, "视频", type="video") == []
    assert [h.id for h in search(db, "视频", type="blog")] == ["b1"]


def test_search_empty_query_returns_empty(tmp_path):
    db = _seed(tmp_path)
    assert search(db, "") == []
    assert search(db, "   ") == []


def test_search_no_match_returns_empty(tmp_path):
    db = _seed(tmp_path)
    assert search(db, "量子计算") == []


def test_search_hit_carries_structured_fields(tmp_path):
    db = _seed(tmp_path)
    hit = search(db, "检索")[0]
    assert hit.type == "video"
    assert hit.author == "作者甲"
    assert isinstance(hit.keywords, list)


def test_search_rejects_bad_mode(tmp_path):
    import pytest
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1", "大语言模型与检索增强生成 RAG")
    sync(data, db)
    with pytest.raises(ValueError):
        search(db, "检索", mode="AND")  # wrong case / unknown mode


def test_search_or_mode_matches_where_and_does_not(tmp_path):
    """OR-mode returns a hit when only SOME bigrams are present in the indexed text.

    Content: title contains "检索增强" (bigrams: 检索, 索增, 增强).
    Query:   "什么是检索增强" → bigrams: 什么, 么是, 是检, 检索, 索增, 增强
    The bigrams 什么 / 么是 / 是检 are NOT in the title, so AND-mode returns nothing.
    OR-mode matches because 检索 / 索增 / 增强 are present.
    """
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "blogs", "b-rag", "检索增强生成简介", summary="介绍检索增强生成技术")
    sync(data, db)

    query = "什么是检索增强"
    # AND mode: fails because the question's leading bigrams are absent
    assert search(db, query) == []
    # OR mode: succeeds because at least some bigrams overlap
    hits = search(db, query, mode="or")
    assert [h.id for h in hits] == ["b-rag"]


# ---------------------------------------------------------------------------
# get_by_ids
# ---------------------------------------------------------------------------

def _seed_direct(db_path):
    con = schema.connect(db_path)
    schema.init_db(con)
    for rid in ("a", "b"):
        con.execute(
            "INSERT INTO items (id, type, title, author, platform, source_url, "
            "published_at, collected_at, summary, keywords, content_hash, synced_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, "video", f"标题{rid}", "作者", "youtube", "https://x/" + rid,
             "2024-01-01", "2024-01-02", "摘要", "[]", "h", "2024-01-02"),
        )
    con.commit()
    con.close()


def test_get_by_ids_returns_mapping(tmp_path):
    db = tmp_path / "atlas.db"
    _seed_direct(db)
    hits = search_mod.get_by_ids(db, ["b", "a", "missing"])
    assert set(hits.keys()) == {"a", "b"}
    assert hits["a"].title == "标题a"
    assert hits["b"].type == "video"


def test_get_by_ids_empty(tmp_path):
    db = tmp_path / "atlas.db"
    _seed_direct(db)
    assert search_mod.get_by_ids(db, []) == {}

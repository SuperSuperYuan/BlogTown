import json

from aishelf.db import schema
from aishelf.db.sync import sync


def _write(data_dir, sub, item_id, **over):
    rec = {
        "id": item_id,
        "type": "video" if sub == "videos" else "blog",
        "title": over.get("title", "标题"),
        "author": over.get("author", "作者甲"),
        "platform": "youtube" if sub == "videos" else "blog",
        "source_url": f"https://x/{item_id}",
        "published_at": over.get("published_at", "2024-01-01"),
        "summary": over.get("summary", "摘要"),
        "keywords": over.get("keywords", ["关键词"]),
        "collected_at": "2024-01-02T00:00:00",
    }
    if sub == "videos":
        rec["thumbnail_url"] = f"https://img/{item_id}.jpg"
    d = data_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _rows(db_path):
    con = schema.connect(db_path)
    return {r["id"]: r for r in con.execute("SELECT * FROM items")}


def test_sync_inserts_rows_and_fts(tmp_path):
    data = tmp_path / "data"
    db = tmp_path / "atlas.db"
    _write(data, "videos", "v1", title="大语言模型")
    _write(data, "blogs", "b1")
    summary = sync(data, db)
    assert (summary.added, summary.updated, summary.removed, summary.unchanged) == (2, 0, 0, 0)
    rows = _rows(db)
    assert set(rows) == {"v1", "b1"}
    assert rows["v1"]["keywords"] == json.dumps(["关键词"], ensure_ascii=False)
    con = schema.connect(db)
    fts = con.execute("SELECT item_id FROM items_fts WHERE items_fts MATCH '\"语言\"'").fetchall()
    assert [r[0] for r in fts] == ["v1"]


def test_sync_unchanged_skips_on_second_run(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1")
    sync(data, db)
    summary = sync(data, db)
    assert (summary.added, summary.updated, summary.unchanged) == (0, 0, 1)


def test_sync_updates_changed_record(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1", title="旧标题")
    sync(data, db)
    _write(data, "videos", "v1", title="新标题")
    summary = sync(data, db)
    assert (summary.added, summary.updated) == (0, 1)
    assert _rows(db)["v1"]["title"] == "新标题"


def test_sync_prunes_deleted_file(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1")
    _write(data, "videos", "v2")
    sync(data, db)
    (data / "videos" / "v1.json").unlink()
    summary = sync(data, db)
    assert summary.removed == 1
    assert set(_rows(db)) == {"v2"}
    con = schema.connect(db)
    assert con.execute("SELECT count(*) FROM items_fts WHERE item_id='v1'").fetchone()[0] == 0


def test_sync_skips_malformed(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1")
    (data / "videos" / "bad.json").write_text("{not json", encoding="utf-8")
    summary = sync(data, db)
    assert summary.added == 1
    assert set(_rows(db)) == {"v1"}

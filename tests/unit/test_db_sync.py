import json

from aishelf import embed
from aishelf.db import schema, vector
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


def _write_note(data_dir, item_id, text):
    d = data_dir / "notes"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(
        json.dumps({"id": item_id, "text": text, "updated_at": "2024-01-03T00:00:00"}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_sync_indexes_note_text_for_search(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    # summary deliberately does NOT contain the term that's only in the note
    _write(data, "videos", "v1", summary="一段普通的摘要")
    _write_note(data, "v1", "里面讲到了向量数据库")
    sync(data, db)
    con = schema.connect(db)
    fts = con.execute("SELECT item_id FROM items_fts WHERE items_fts MATCH '\"向量\"'").fetchall()
    assert [r[0] for r in fts] == ["v1"]


def test_sync_reindexes_when_note_changes(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1", summary="普通摘要")
    sync(data, db)  # no note yet
    _write_note(data, "v1", "新增了关于强化学习的笔记")
    summary = sync(data, db)
    assert summary.updated == 1  # note change marks the item as updated
    con = schema.connect(db)
    fts = con.execute("SELECT item_id FROM items_fts WHERE items_fts MATCH '\"强化\"'").fetchall()
    assert [r[0] for r in fts] == ["v1"]


def test_sync_tolerates_non_dict_note_json(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1")
    notes = data / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "v1.json").write_text("[]", encoding="utf-8")  # valid JSON, not a dict
    summary = sync(data, db)  # must not raise
    assert summary.added == 1
    assert set(_rows(db)) == {"v1"}


# ---------------------------------------------------------------------------
# Embedding tests (Task 6)
# ---------------------------------------------------------------------------

def _write_video(data_dir, vid, summary="普通摘要"):
    (data_dir / "videos").mkdir(parents=True, exist_ok=True)
    rec = {"id": vid, "type": "video", "title": "标题", "author": "作者甲",
           "platform": "youtube", "source_url": f"https://x/{vid}",
           "published_at": "2024-01-01", "summary": summary, "keywords": [],
           "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}
    (data_dir / "videos" / f"{vid}.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _embedding_row(db_path, vid):
    con = schema.connect(db_path)
    row = con.execute(
        "SELECT embedding, embedding_model, embedding_dim FROM items WHERE id=?", (vid,)
    ).fetchone()
    con.close()
    return row


def test_sync_stores_embeddings_when_configured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])
    sync(data, db)
    row = _embedding_row(db, "v1")
    assert row["embedding"] is not None
    assert row["embedding_model"] == "fake-embed"
    assert row["embedding_dim"] == 3
    assert list(vector.unpack(row["embedding"])) == [1.0, 0.0, 0.0]


def test_sync_skips_embeddings_when_not_configured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    # embed_texts must never be called when unconfigured:
    monkeypatch.setattr(embed, "embed_texts", lambda texts: (_ for _ in ()).throw(AssertionError("called")))
    sync(data, db)
    assert _embedding_row(db, "v1")["embedding"] is None


def test_sync_reembeds_on_model_change(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "model-A")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    sync(data, db)
    assert _embedding_row(db, "v1")["embedding_model"] == "model-A"
    # Same content, new model -> re-embed even though the content hash is unchanged.
    calls = {"n": 0}
    def _embed(texts):
        calls["n"] += 1
        return [[0.0, 1.0] for _ in texts]
    monkeypatch.setattr(embed, "model_name", lambda: "model-B")
    monkeypatch.setattr(embed, "embed_texts", _embed)
    sync(data, db)
    row = _embedding_row(db, "v1")
    assert calls["n"] == 1
    assert row["embedding_model"] == "model-B"
    assert list(vector.unpack(row["embedding"])) == [0.0, 1.0]


def test_sync_embedding_failure_leaves_row_without_crash(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: None)  # service down
    summary = sync(data, db)          # must not raise
    assert summary.added == 1
    assert _embedding_row(db, "v1")["embedding"] is None


def test_sync_skips_embedding_on_vector_count_mismatch(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    _write_video(data, "v2")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0]])  # too few (1 for 2)
    summary = sync(data, db)  # must not raise
    assert summary.added == 2
    assert _embedding_row(db, "v1")["embedding"] is None
    assert _embedding_row(db, "v2")["embedding"] is None

import json

from aishelf import embed
from aishelf import alias as _alias
from aishelf.db import schema, vector, graph as _graph
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


def test_sync_unchanged_skips_on_second_run(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: False)
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


# ---------------------------------------------------------------------------
# Knowledge-graph edge tests (Task 5)
# ---------------------------------------------------------------------------

def _edges(db_path):
    con = schema.connect(db_path)
    rows = {(r["src"], r["dst"]) for r in con.execute("SELECT src, dst FROM edges")}
    con.close()
    return rows


def test_sync_builds_edges_for_similar_items(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    _write_video(data, "v2")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0], [0.98, 0.2]][: len(texts)])
    monkeypatch.setattr(_graph, "GRAPH_SIM_FLOOR", 0.5)
    sync(data, db)
    assert _edges(db) == {("v1", "v2")}


def test_sync_no_edges_when_embeddings_unconfigured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    _write_video(data, "v2")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    sync(data, db)
    assert _edges(db) == set()


def test_sync_drops_edges_for_removed_item(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    _write_video(data, "v2")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0], [0.98, 0.2]][: len(texts)])
    monkeypatch.setattr(_graph, "GRAPH_SIM_FLOOR", 0.5)
    sync(data, db)
    assert _edges(db) == {("v1", "v2")}
    (data / "videos" / "v2.json").unlink()   # delete one item's file
    sync(data, db)
    assert _edges(db) == set()                # its edge is gone


# ---------------------------------------------------------------------------
# Alias tests (Task 3)
# ---------------------------------------------------------------------------

def _alias_of(db_path, vid):
    con = schema.connect(db_path)
    row = con.execute("SELECT alias FROM items WHERE id=?", (vid,)).fetchone()
    con.close()
    return row["alias"]


def test_sync_stores_alias_for_new_item(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)              # isolate alias
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: ["别名一"] * len(pairs))
    sync(data, db)
    assert _alias_of(db, "v1") == "别名一"


def test_sync_skips_alias_when_unconfigured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: False)
    sync(data, db)
    assert _alias_of(db, "v1") is None


def test_sync_regenerates_alias_on_title_change_not_note(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    calls = {"n": 0}

    def _gen(pairs):
        calls["n"] += 1
        return [f"别名{calls['n']}"] * len(pairs)

    monkeypatch.setattr(_alias, "generate_aliases", _gen)
    sync(data, db)
    assert calls["n"] == 1 and _alias_of(db, "v1") == "别名1"

    # note-only change: alias must NOT regenerate
    (data / "notes").mkdir(exist_ok=True)
    (data / "notes" / "v1.json").write_text(
        json.dumps({"id": "v1", "text": "新笔记", "updated_at": "2024-02-01"}, ensure_ascii=False),
        encoding="utf-8")
    sync(data, db)
    assert calls["n"] == 1 and _alias_of(db, "v1") == "别名1"

    # title change: alias regenerates
    rec = json.loads((data / "videos" / "v1.json").read_text(encoding="utf-8"))
    rec["title"] = "全新的标题"
    (data / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    sync(data, db)
    assert calls["n"] == 2 and _alias_of(db, "v1") == "别名2"


def test_sync_backfills_missing_alias_without_title_change(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)        # first sync: gen fails
    sync(data, db)
    assert _alias_of(db, "v1") is None
    # same title, generation now works -> alias backfilled (missing-alias retry, no title change)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: ["补的别名"] * len(pairs))
    sync(data, db)
    assert _alias_of(db, "v1") == "补的别名"


# ---------------------------------------------------------------------------
# Hook tests (一句话钩子)
# ---------------------------------------------------------------------------

def _hook_of(db_path, vid):
    con = schema.connect(db_path)
    row = con.execute("SELECT hook FROM items WHERE id=?", (vid,)).fetchone()
    con.close()
    return row["hook"]


def test_sync_stores_hook_for_new_item(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)
    monkeypatch.setattr(_alias, "generate_hooks", lambda pairs: ["为什么值得看"] * len(pairs))
    sync(data, db)
    assert _hook_of(db, "v1") == "为什么值得看"


def test_sync_skips_hook_when_unconfigured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: False)
    sync(data, db)
    assert _hook_of(db, "v1") is None


def test_sync_regenerates_hook_on_title_change_not_note(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)
    calls = {"n": 0}

    def _gen(pairs):
        calls["n"] += 1
        return [f"钩子{calls['n']}"] * len(pairs)

    monkeypatch.setattr(_alias, "generate_hooks", _gen)
    sync(data, db)
    assert calls["n"] == 1 and _hook_of(db, "v1") == "钩子1"

    # note-only change: hook must NOT regenerate
    (data / "notes").mkdir(exist_ok=True)
    (data / "notes" / "v1.json").write_text(
        json.dumps({"id": "v1", "text": "新笔记", "updated_at": "2024-02-01"}, ensure_ascii=False),
        encoding="utf-8")
    sync(data, db)
    assert calls["n"] == 1 and _hook_of(db, "v1") == "钩子1"

    # title change: hook regenerates
    rec = json.loads((data / "videos" / "v1.json").read_text(encoding="utf-8"))
    rec["title"] = "全新的标题"
    (data / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    sync(data, db)
    assert calls["n"] == 2 and _hook_of(db, "v1") == "钩子2"


def test_sync_backfills_missing_hook_without_title_change(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)
    monkeypatch.setattr(_alias, "generate_hooks", lambda pairs: None)  # first sync: gen fails
    sync(data, db)
    assert _hook_of(db, "v1") is None
    # same title, generation now works -> hook backfilled
    monkeypatch.setattr(_alias, "generate_hooks", lambda pairs: ["补的钩子"] * len(pairs))
    sync(data, db)
    assert _hook_of(db, "v1") == "补的钩子"


# ---------------------------------------------------------------------------
# Cluster tests (主题星系)
# ---------------------------------------------------------------------------

def _cluster_of(db_path, vid):
    con = schema.connect(db_path)
    row = con.execute("SELECT cluster FROM items WHERE id=?", (vid,)).fetchone()
    con.close()
    return row["cluster"]


def test_sync_clusters_items_when_embeddings_configured(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    # 4 items in two clearly-separated groups -> choose_k(4) == 3, so the
    # multi-cluster path is exercised (not the trivial k=1 single-cluster case).
    vecs = [[1.0, 0.0], [0.97, 0.2], [-1.0, 0.0], [-0.98, 0.1]]
    for i in range(4):
        _write_video(data, f"v{i + 1}")
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: vecs[: len(texts)])
    monkeypatch.setattr(_alias, "is_configured", lambda: False)   # isolate clustering from naming
    sync(data, db)
    assert all(_cluster_of(db, f"v{i + 1}") is not None for i in range(4))  # every item assigned
    con = schema.connect(db)
    n_clusters = con.execute("SELECT count(*) FROM clusters").fetchone()[0]
    assigned = con.execute("SELECT count(DISTINCT cluster) FROM items").fetchone()[0]
    con.close()
    assert n_clusters >= 2 and n_clusters == assigned   # real multi-cluster split, table matches assignments


def test_sync_no_clusters_when_embeddings_unconfigured(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: False)
    sync(data, db)
    assert _cluster_of(db, "v1") is None
    con = schema.connect(db)
    assert con.execute("SELECT count(*) FROM clusters").fetchone()[0] == 0
    con.close()


def test_sync_names_clusters_when_alias_configured(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    _write_video(data, "v2")
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0], [0.97, 0.2]][: len(texts)])
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)
    monkeypatch.setattr(_alias, "generate_hooks", lambda pairs: None)
    monkeypatch.setattr(_alias, "generate_cluster_names", lambda clusters: ["星系名"] * len(clusters))
    sync(data, db)
    con = schema.connect(db)
    names = [r["name"] for r in con.execute("SELECT name FROM clusters")]
    con.close()
    assert names and all(n == "星系名" for n in names)


def test_sync_note_edit_does_not_rename_clusters(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    _write_video(data, "v2")
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0], [0.97, 0.2]][: len(texts)])
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)
    monkeypatch.setattr(_alias, "generate_hooks", lambda pairs: None)
    calls = {"n": 0}

    def _name(clusters):
        calls["n"] += 1
        return ["星系名"] * len(clusters)

    monkeypatch.setattr(_alias, "generate_cluster_names", _name)
    sync(data, db)
    assert calls["n"] == 1
    _write_note(data, "v1", "新增一段笔记")
    sync(data, db)
    assert calls["n"] == 1

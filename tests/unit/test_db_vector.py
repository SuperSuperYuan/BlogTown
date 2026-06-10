import numpy as np

from aishelf.db import schema, vector


def test_items_table_has_embedding_columns(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
    con.close()
    assert {"embedding", "embedding_model", "embedding_dim"} <= cols


def test_pack_unpack_roundtrip():
    blob = vector.pack([1.0, 2.5, -3.0])
    out = vector.unpack(blob)
    assert isinstance(out, np.ndarray)
    assert out.dtype == np.float32
    assert list(out) == [1.0, 2.5, -3.0]


def _seed(db_path, rows):
    # rows: list of (id, type, vec or None)
    con = schema.connect(db_path)
    schema.init_db(con)
    for rid, typ, vec in rows:
        con.execute(
            "INSERT INTO items (id, type, title, author, platform, source_url, "
            "published_at, collected_at, summary, keywords, embedding, embedding_model, "
            "embedding_dim, content_hash, synced_at) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, typ, "t", "a", "p", "u", "2024-01-01", "2024-01-02", "s", "[]",
             vector.pack(vec) if vec else None, "m" if vec else None,
             len(vec) if vec else None, "h", "2024-01-02"),
        )
    con.commit()
    con.close()


def test_load_embeddings_filters_by_dim_and_nulls(tmp_path):
    db = tmp_path / "atlas.db"
    _seed(db, [
        ("a", "video", [1.0, 0.0]),
        ("b", "blog", [0.0, 1.0]),
        ("c", "video", None),          # no embedding -> excluded
        ("d", "video", [1.0, 0.0, 0.0]),  # wrong dim -> excluded
    ])
    ids, mat = vector.load_embeddings(db, 2)
    assert set(ids) == {"a", "b"}
    assert mat.shape == (2, 2)


def test_load_embeddings_type_filter(tmp_path):
    db = tmp_path / "atlas.db"
    _seed(db, [("a", "video", [1.0, 0.0]), ("b", "blog", [0.0, 1.0])])
    ids, _ = vector.load_embeddings(db, 2, type="video")
    assert ids == ["a"]


def test_cosine_search_orders_by_similarity():
    ids = ["a", "b", "c"]
    mat = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32)
    out = vector.cosine_search([1.0, 0.0], ids, mat, top_n=2)
    assert [i for i, _ in out] == ["a", "b"]
    assert out[0][1] > out[1][1]


def test_cosine_search_empty():
    out = vector.cosine_search([1.0, 0.0], [], np.empty((0, 2), dtype=np.float32), top_n=5)
    assert out == []

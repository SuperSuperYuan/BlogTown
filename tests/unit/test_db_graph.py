from aishelf.db import schema


def test_edges_table_created(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    names = {r["name"] for r in con.execute("PRAGMA table_info(edges)")}
    con.close()
    assert names == {"src", "dst", "weight"}


import numpy as np

from aishelf.db import graph


def test_neighbors_threshold_sorted_and_excludes_self():
    ids = ["a", "b", "c"]
    mat = np.array([[1.0, 0.0], [0.96, 0.28], [0.0, 1.0]], dtype=np.float32)  # a~b high, a~c 0
    out = graph.neighbors([1.0, 0.0], ids, mat, floor=0.5, exclude="a")
    assert [i for i, _ in out] == ["b"]          # c below floor, a excluded
    assert out[0][1] > 0.9


def test_neighbors_empty():
    assert graph.neighbors([1.0, 0.0], [], np.empty((0, 2), dtype=np.float32), floor=0.5) == []


def test_canon_orders_pair():
    assert graph._canon("b", "a") == ("a", "b")
    assert graph._canon("a", "b") == ("a", "b")


def _seed_item(con, rid, typ, vec):
    con.execute(
        "INSERT INTO items (id, type, title, author, platform, source_url, "
        "published_at, collected_at, summary, keywords, embedding, embedding_model, "
        "embedding_dim, content_hash, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, typ, f"标题{rid}", "作者", "p", f"https://x/{rid}", "2024-01-01",
         "2024-01-02", "s", "[]", graph.vector.pack(vec), "m", len(vec), "h", "2024-01-02"),
    )


def _edge_set(con):
    return {(r["src"], r["dst"]) for r in con.execute("SELECT src, dst FROM edges")}


def test_recompute_edges_for_new_item(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0])
    _seed_item(con, "b", "blog", [0.97, 0.24])   # close to a
    _seed_item(con, "c", "video", [0.0, 1.0])    # far from a
    graph.recompute_edges_for(con, ["a", "b", "c"], floor=0.5)
    assert _edge_set(con) == {("a", "b")}        # only a-b clears the floor, stored canonically
    con.close()


def test_recompute_is_incremental_and_symmetric(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0])
    graph.recompute_edges_for(con, ["a"], floor=0.5)      # no neighbors yet
    assert _edge_set(con) == set()
    _seed_item(con, "b", "blog", [0.97, 0.24])
    graph.recompute_edges_for(con, ["b"], floor=0.5)      # adding b links a-b
    assert _edge_set(con) == {("a", "b")}
    con.close()


def test_delete_edges_for_removes_incident(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0])
    _seed_item(con, "b", "blog", [0.97, 0.24])
    graph.recompute_edges_for(con, ["a", "b"], floor=0.5)
    graph.delete_edges_for(con, ["b"])
    assert _edge_set(con) == set()
    con.close()


def test_load_graph_shape_and_degree(tmp_path):
    db = tmp_path / "atlas.db"
    con = schema.connect(db)
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0])
    _seed_item(con, "b", "blog", [0.97, 0.24])
    graph.recompute_edges_for(con, ["a", "b"], floor=0.5)
    con.commit(); con.close()
    g = graph.load_graph(db, cap_k=8)
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"a", "b"}
    a = next(n for n in g["nodes"] if n["id"] == "a")
    assert a["type"] == "video" and a["title"] == "标题a" and a["degree"] == 1
    assert g["edges"] == [{"source": "a", "target": "b", "weight": g["edges"][0]["weight"]}]
    assert g["edges"][0]["weight"] > 0.9


def test_load_graph_caps_top_k(tmp_path):
    # Union top-K: an edge is dropped only when it is outside the top-K of BOTH
    # endpoints. Here a-d (0.5) is the weakest for a AND for d, and both have two
    # stronger edges, so with cap_k=2 a-d is dropped while the other four survive.
    db = tmp_path / "atlas.db"
    con = schema.connect(db)
    schema.init_db(con)
    for src, dst, w in [("a", "b", 0.9), ("a", "c", 0.85), ("a", "d", 0.5),
                        ("b", "d", 0.9), ("c", "d", 0.85)]:
        con.execute("INSERT INTO edges (src, dst, weight) VALUES (?,?,?)", (src, dst, w))
    for rid in ("a", "b", "c", "d"):
        _seed_item(con, rid, "blog", [1.0, 0.0])
    con.commit(); con.close()
    g = graph.load_graph(db, cap_k=2)
    kept = {(e["source"], e["target"]) for e in g["edges"]}
    assert ("a", "d") not in kept                       # outside top-2 of both a and d
    assert kept == {("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")}


def test_load_graph_empty(tmp_path):
    db = tmp_path / "atlas.db"
    con = schema.connect(db); schema.init_db(con); con.close()
    assert graph.load_graph(db) == {"nodes": [], "edges": []}


def test_load_graph_drops_orphan_edges(tmp_path):
    # An edge whose endpoint has no item row must not appear in the output
    # (it would make the frontend graph library throw on a missing node).
    db = tmp_path / "atlas.db"
    con = schema.connect(db)
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0])
    con.execute("INSERT INTO edges (src, dst, weight) VALUES ('a','ghost',0.9)")
    con.commit(); con.close()
    g = graph.load_graph(db)
    assert g["edges"] == []                                   # orphan edge dropped
    assert next(n for n in g["nodes"] if n["id"] == "a")["degree"] == 0


def test_items_table_has_alias_column(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
    con.close()
    assert "alias" in cols

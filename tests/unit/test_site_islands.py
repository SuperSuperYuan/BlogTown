from aishelf.site import islands


def _item(id, type="video", title=None, hook=None):
    return {"id": id, "type": type, "title": title or id, "hook": hook}


def test_degree_and_lone_weak_split():
    items = [_item("a"), _item("b"), _item("c"), _item("d")]
    edges = [("a", "b"), ("a", "c")]   # a deg2, b deg1, c deg1, d deg0
    out = islands.build_islands(items, edges)
    assert [e["id"] for e in out["lone"]] == ["d"]
    assert {e["id"] for e in out["weak"]} == {"a", "b", "c"}
    assert out["stats"] == {"embedded": 4, "lone": 1, "weak": 3, "connected": 0}


def test_connected_excluded_above_max():
    items = [_item(x) for x in ["h", "n1", "n2", "n3"]]
    edges = [("h", "n1"), ("h", "n2"), ("h", "n3")]   # h deg3 -> connected
    out = islands.build_islands(items, edges)
    ids = {e["id"] for e in out["weak"]} | {e["id"] for e in out["lone"]}
    assert "h" not in ids
    assert {e["id"] for e in out["weak"]} == {"n1", "n2", "n3"}
    assert out["stats"]["connected"] == 1


def test_weak_neighbors_resolved_and_sorted():
    items = [_item("x", title="X"), _item("a", title="Apple", type="blog"),
             _item("m", title="Mango")]
    edges = [("x", "m"), ("x", "a")]   # x deg2 weak; a,m deg1 weak
    out = islands.build_islands(items, edges)
    xe = next(e for e in out["weak"] if e["id"] == "x")
    assert [n["title"] for n in xe["neighbors"]] == ["Apple", "Mango"]
    assert xe["neighbors"][0]["type"] == "blog"
    assert xe["degree"] == 2


def test_dirty_edge_endpoint_not_in_items_skipped():
    items = [_item("a"), _item("b")]
    edges = [("a", "ghost"), ("a", "b")]   # ghost not in items
    out = islands.build_islands(items, edges)
    a = next(e for e in out["weak"] if e["id"] == "a")
    assert [n["id"] for n in a["neighbors"]] == ["b"]


def test_hook_defaults_empty():
    out = islands.build_islands([_item("a", hook=None)], [])
    assert out["lone"][0]["hook"] == ""


def test_lone_sorted_by_title():
    items = [_item("a", title="Zebra"), _item("b", title="Ant")]
    out = islands.build_islands(items, [])
    assert [e["title"] for e in out["lone"]] == ["Ant", "Zebra"]


def test_weak_sorted_by_degree_then_title():
    # p deg2 (q,r); q deg1 (p); r deg1 (p) -> weak order: q,r (deg1), then p (deg2)
    items = [_item("p", title="P"), _item("q", title="Q"), _item("r", title="R")]
    edges = [("p", "q"), ("p", "r")]
    out = islands.build_islands(items, edges)
    assert [e["id"] for e in out["weak"]] == ["q", "r", "p"]


def test_empty_input():
    out = islands.build_islands([], [])
    assert out == {"lone": [], "weak": [],
                   "stats": {"embedded": 0, "lone": 0, "weak": 0, "connected": 0}}


from aishelf.db import schema as db_schema

_ITEM_COLS = ["id", "type", "title", "author", "platform", "source_url",
              "published_at", "collected_at", "summary", "keywords",
              "content_hash", "synced_at", "embedding", "hook"]


def _insert(con, *, id, type="video", title="t", hook=None, embedding=b"x"):
    vals = {"id": id, "type": type, "title": title, "author": "A", "platform": "p",
            "source_url": "https://x", "published_at": "2026-01-01T00:00:00",
            "collected_at": "2026-01-01T00:00:00", "summary": "s", "keywords": "[]",
            "content_hash": "h", "synced_at": "2026-01-01T00:00:00",
            "embedding": embedding, "hook": hook}
    con.execute(f"INSERT INTO items ({','.join(_ITEM_COLS)}) VALUES "
                f"({','.join('?'*len(_ITEM_COLS))})", [vals[c] for c in _ITEM_COLS])


def _edge(con, a, b, w=0.7):
    s, d = (a, b) if a < b else (b, a)
    con.execute("INSERT INTO edges (src,dst,weight) VALUES (?,?,?)", (s, d, w))


def _seed_islands(db_path):
    con = db_schema.connect(db_path)
    db_schema.init_db(con)
    _insert(con, id="a", title="A")
    _insert(con, id="b", title="B")
    _insert(con, id="c", title="C")
    _insert(con, id="noemb", title="NoEmb", embedding=None)   # excluded
    _edge(con, "a", "b")
    con.commit(); con.close()


def test_load_islands_reads_db(tmp_path):
    db = str(tmp_path / "atlas.db")
    _seed_islands(db)
    out = islands.load_islands(db)
    assert out["stats"]["embedded"] == 3            # a,b,c (noemb excluded)
    assert [e["id"] for e in out["lone"]] == ["c"]  # c deg0
    assert {e["id"] for e in out["weak"]} == {"a", "b"}


def test_load_islands_excludes_unembedded(tmp_path):
    db = str(tmp_path / "atlas.db")
    _seed_islands(db)
    out = islands.load_islands(db)
    ids = {e["id"] for e in out["lone"]} | {e["id"] for e in out["weak"]}
    assert "noemb" not in ids


def test_load_islands_missing_db_empty(tmp_path):
    out = islands.load_islands(str(tmp_path / "nope.db"))
    assert out["stats"]["embedded"] == 0
    assert out["lone"] == [] and out["weak"] == []


def test_load_islands_old_db_missing_columns_empty(tmp_path):
    db = str(tmp_path / "old.db")
    con = db_schema.connect(db)
    con.execute("CREATE TABLE items (id TEXT)")   # no embedding column
    con.commit(); con.close()
    assert islands.load_islands(db)["stats"]["embedded"] == 0

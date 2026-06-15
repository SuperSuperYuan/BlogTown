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

from aishelf.db import schema


def test_edges_table_created(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    names = {r["name"] for r in con.execute("PRAGMA table_info(edges)")}
    con.close()
    assert names == {"src", "dst", "weight"}

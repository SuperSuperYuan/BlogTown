from aishelf.db import schema


def test_items_table_has_embedding_columns(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
    con.close()
    assert {"embedding", "embedding_model", "embedding_dim"} <= cols

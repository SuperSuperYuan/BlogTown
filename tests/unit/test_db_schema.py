from aishelf.db import schema


def _tables(con):
    rows = con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
    return {r[0] for r in rows}


def test_init_db_creates_items_and_fts(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    names = _tables(con)
    assert "items" in names
    assert "items_fts" in names


def test_init_db_is_idempotent(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    schema.init_db(con)  # second call must not raise
    assert "items" in _tables(con)


def test_connect_creates_parent_dirs(tmp_path):
    nested = tmp_path / "a" / "b" / "atlas.db"
    con = schema.connect(nested)
    schema.init_db(con)
    assert nested.exists()


def test_fts_matches_after_insert(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    con.execute(
        "INSERT INTO items_fts (item_id, title, summary, keywords, author) "
        "VALUES ('x', '语言 模型', 's', 'k', 'a')"
    )
    rows = con.execute("SELECT item_id FROM items_fts WHERE items_fts MATCH '\"语言\"'").fetchall()
    assert [r[0] for r in rows] == ["x"]

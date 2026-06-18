from aishelf.site import learn


_ITEMS = [
    {"id": "v1", "title": "推理模型入门", "summary": "什么是推理模型。", "type": "video"},
    {"id": "v2", "title": "测试时计算", "summary": "推理阶段扩展算力。", "type": "video"},
    {"id": "b1", "title": "思维链评测", "summary": "如何评测推理。", "type": "blog"},
]


def test_build_messages_shape_and_content():
    msgs = learn.build_messages("推理模型", _ITEMS)
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "顺序" in system or "进阶" in system
    assert "标题" in system
    assert "Markdown" in system or "markdown" in system
    assert "推理模型" in user
    assert "推理模型入门" in user and "思维链评测" in user


from aishelf.db import schema as db_schema

_ITEM_COLS = ["id", "type", "title", "author", "platform", "source_url",
              "published_at", "collected_at", "summary", "keywords",
              "content_hash", "synced_at", "cluster"]


def _insert_item(con, *, id, title="t", summary="s", type="video", cluster=None):
    vals = {"id": id, "type": type, "title": title, "author": "A", "platform": "p",
            "source_url": "https://x", "published_at": "2026-01-01T00:00:00",
            "collected_at": "2026-01-01T00:00:00", "summary": summary,
            "keywords": "[]", "content_hash": "h", "synced_at": "2026-01-01T00:00:00",
            "cluster": cluster}
    con.execute(f"INSERT INTO items ({','.join(_ITEM_COLS)}) VALUES "
                f"({','.join('?'*len(_ITEM_COLS))})", [vals[c] for c in _ITEM_COLS])


def _seed(db_path):
    con = db_schema.connect(db_path)
    db_schema.init_db(con)
    con.execute("INSERT INTO clusters (id,name,color,signature) VALUES (0,'推理','#ff9a3c','s0')")
    con.execute("INSERT INTO clusters (id,name,color,signature) VALUES (1,'多模态','#4cc2ff','s1')")
    _insert_item(con, id="v1", title="推理一", summary="基础", type="video", cluster=0)
    _insert_item(con, id="v2", title="推理二", summary="进阶", type="video", cluster=0)
    _insert_item(con, id="b1", title="推理三", summary="纵深", type="blog", cluster=0)
    _insert_item(con, id="v3", title="多模态一", summary="看图", type="video", cluster=1)
    con.commit(); con.close()


def test_load_galaxies_aggregates(tmp_path):
    db = str(tmp_path / "atlas.db")
    _seed(db)
    gs = learn.load_galaxies(db)
    assert [g.name for g in gs] == ["推理", "多模态"]
    assert [g.size for g in gs] == [3, 1]
    assert gs[0].id == 0 and gs[0].color == "#ff9a3c"
    titles = [it.title for it in gs[0].items]
    assert set(titles) == {"推理一", "推理二", "推理三"}
    assert gs[0].items[0].summary in {"基础", "进阶", "纵深"}
    assert gs[0].items[0].type in {"video", "blog"}


def test_load_galaxies_empty_when_no_clusters(tmp_path):
    db = str(tmp_path / "atlas.db")
    con = db_schema.connect(db); db_schema.init_db(con)
    _insert_item(con, id="x", cluster=None)
    con.commit(); con.close()
    assert learn.load_galaxies(db) == []


def test_load_galaxies_empty_when_db_missing(tmp_path):
    assert learn.load_galaxies(str(tmp_path / "nope.db")) == []

from aishelf.site import mirror


def _profile():
    return mirror.Profile(
        galaxies=[
            mirror.Galaxy(name="推理模型", color="#ff9a3c", size=12, recent=4,
                          titles=["o1 深度解析", "测试时计算", "思维链评测"]),
            mirror.Galaxy(name="多模态", color="#4cc2ff", size=3, recent=0,
                          titles=["看图说话", "视频理解"]),
        ],
        total=15, videos=9, blogs=6,
        top_authors=[("Karpathy", 4), ("OpenAI", 3)],
        span_days=120, recent_n=10,
    )


def test_build_messages_shape_and_content():
    msgs = mirror.build_messages(_profile())
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    for tag in ["【你的主线】", "【最近的转向】", "【一个盲区】", "【一句话人格】"]:
        assert tag in system
    assert "Markdown" in system or "markdown" in system
    assert "推理模型" in user and "多模态" in user
    assert "12" in user and "o1 深度解析" in user
    assert "Karpathy" in user


from aishelf.db import schema as db_schema

_ITEM_COLS = ["id", "type", "title", "author", "platform", "source_url",
              "published_at", "collected_at", "summary", "keywords",
              "content_hash", "synced_at", "cluster"]


def _insert_item(con, *, id, type="video", title="t", author="A",
                 collected_at="2026-01-01T00:00:00", cluster=None):
    vals = {
        "id": id, "type": type, "title": title, "author": author,
        "platform": "p", "source_url": "https://x", "published_at": collected_at,
        "collected_at": collected_at, "summary": "s", "keywords": "[]",
        "content_hash": "h", "synced_at": collected_at, "cluster": cluster,
    }
    placeholders = ",".join("?" for _ in _ITEM_COLS)
    con.execute(f"INSERT INTO items ({','.join(_ITEM_COLS)}) VALUES ({placeholders})",
                [vals[c] for c in _ITEM_COLS])


def _seed(db_path):
    con = db_schema.connect(db_path)
    db_schema.init_db(con)
    con.execute("INSERT INTO clusters (id, name, color, signature) VALUES (0,'推理','#ff9a3c','s0')")
    con.execute("INSERT INTO clusters (id, name, color, signature) VALUES (1,'多模态','#4cc2ff','s1')")
    rows = [
        ("v1", "video", "A", "2026-01-01T00:00:00", "推理一", 0),
        ("v2", "video", "A", "2026-02-01T00:00:00", "推理二", 0),
        ("b1", "blog",  "B", "2026-03-01T00:00:00", "推理三", 0),
        ("v3", "video", "B", "2026-05-01T00:00:00", "多模态一", 1),
    ]
    for id_, type_, author, collected, title, cluster in rows:
        _insert_item(con, id=id_, type=type_, title=title, author=author,
                     collected_at=collected, cluster=cluster)
    con.commit()
    con.close()


def test_load_profile_aggregates(tmp_path):
    db = str(tmp_path / "atlas.db")
    _seed(db)
    p = mirror.load_profile(db, recent_n=2)
    assert p is not None
    assert [g.name for g in p.galaxies] == ["推理", "多模态"]
    assert [g.size for g in p.galaxies] == [3, 1]
    by_name = {g.name: g for g in p.galaxies}
    assert by_name["多模态"].recent == 1
    assert by_name["推理"].recent == 1
    assert p.total == 4 and p.videos == 3 and p.blogs == 1
    assert p.galaxies[0].titles
    assert by_name["多模态"].color == "#4cc2ff"
    assert p.span_days >= 1


def test_load_profile_none_when_no_clusters(tmp_path):
    db = str(tmp_path / "atlas.db")
    con = db_schema.connect(db)
    db_schema.init_db(con)
    _insert_item(con, id="x", cluster=None)
    con.commit(); con.close()
    assert mirror.load_profile(db) is None


def test_load_profile_none_when_db_missing(tmp_path):
    assert mirror.load_profile(str(tmp_path / "nope.db")) is None


import aishelf.site.app as app_module
from aishelf.site.app import app
from fastapi.testclient import TestClient


def test_mirror_page_renders():
    client = TestClient(app)
    r = client.get("/mirror")
    assert r.status_code == 200
    assert "藏书镜" in r.text


def test_mirror_chat_streams_profile_then_deltas(tmp_path, monkeypatch):
    # default DB path is <data_dir>/atlas.db, so seed directly there
    _seed(str(tmp_path / "atlas.db"))
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_module.llm, "stream_completion",
                        lambda messages: iter([app_module.hermes.sse({"delta": "你是"}),
                                               app_module.hermes.sse({"done": True})]))
    client = TestClient(app)
    body = client.post("/mirror/chat").text
    assert '"profile"' in body
    assert "推理" in body
    assert "你是" in body


def test_mirror_chat_error_when_no_clusters(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    con = db_schema.connect(str(tmp_path / "atlas.db"))
    db_schema.init_db(con)
    _insert_item(con, id="x", cluster=None)
    con.commit(); con.close()
    client = TestClient(app)
    body = client.post("/mirror/chat").text
    assert '"error"' in body


def test_topbar_has_mirror_link():
    client = TestClient(app)
    r = client.get("/mirror")
    assert 'href="/mirror"' in r.text


def test_mirror_page_has_action_button():
    client = TestClient(app)
    r = client.get("/mirror")
    assert "照一照" in r.text

from aishelf.site import timeline


def _item(id, collected_at, cluster=None, hook=None, type="video", title=None):
    return {"id": id, "type": type, "title": title or id,
            "collected_at": collected_at, "cluster": cluster, "hook": hook}


CLUSTERS = {
    0: {"name": "推理", "color": "#ff9a3c"},
    1: {"name": "多模态", "color": "#4cc2ff"},
}


def test_groups_by_month_in_desc_order():
    items = [
        _item("a", "2026-04-10T00:00:00", cluster=0),
        _item("b", "2026-06-02T00:00:00", cluster=0),
        _item("c", "2026-06-20T00:00:00", cluster=1),
    ]
    out = timeline.build_timeline(items, CLUSTERS)
    assert [m["title"] for m in out["months"]] == ["2026年6月", "2026年4月"]
    june = out["months"][0]
    assert june["count"] == 2
    # newest first within the month
    assert [it["id"] for it in june["items"]] == ["c", "b"]


def test_item_carries_cluster_name_color_and_hook():
    items = [_item("a", "2026-06-01T00:00:00", cluster=1, hook="值得看")]
    it = timeline.build_timeline(items, CLUSTERS)["months"][0]["items"][0]
    assert it["cluster_name"] == "多模态"
    assert it["cluster_color"] == "#4cc2ff"
    assert it["hook"] == "值得看"


def test_unclassified_and_missing_hook():
    items = [_item("a", "2026-06-01T00:00:00", cluster=None, hook=None)]
    it = timeline.build_timeline(items, CLUSTERS)["months"][0]["items"][0]
    assert it["cluster_name"] == "未归类"
    assert it["cluster_color"] == timeline.UNCLASSIFIED_COLOR
    assert it["hook"] == ""


def test_unknown_cluster_id_falls_back_to_unclassified():
    items = [_item("a", "2026-06-01T00:00:00", cluster=99)]
    it = timeline.build_timeline(items, CLUSTERS)["months"][0]["items"][0]
    assert it["cluster_name"] == "未归类"


def test_stats_total_and_span_multi_month():
    items = [
        _item("a", "2026-04-10T00:00:00", cluster=0),
        _item("b", "2026-06-20T00:00:00", cluster=1),
    ]
    stats = timeline.build_timeline(items, CLUSTERS)["stats"]
    assert stats["total"] == 2
    assert stats["span"] == "2026年4月 – 2026年6月"


def test_stats_span_single_month():
    items = [_item("a", "2026-06-10T00:00:00", cluster=0)]
    assert timeline.build_timeline(items, CLUSTERS)["stats"]["span"] == "2026年6月"


def test_stats_top_galaxy_excludes_unclassified_and_counts():
    items = [
        _item("a", "2026-06-01T00:00:00", cluster=0),
        _item("b", "2026-06-02T00:00:00", cluster=0),
        _item("c", "2026-06-03T00:00:00", cluster=1),
        _item("d", "2026-06-04T00:00:00", cluster=None),
    ]
    top = timeline.build_timeline(items, CLUSTERS)["stats"]["top_galaxy"]
    assert top == {"name": "推理", "color": "#ff9a3c", "count": 2}


def test_legend_count_desc_with_unclassified_last():
    items = [
        _item("a", "2026-06-01T00:00:00", cluster=1),
        _item("b", "2026-06-02T00:00:00", cluster=0),
        _item("c", "2026-06-03T00:00:00", cluster=0),
        _item("d", "2026-06-04T00:00:00", cluster=None),
    ]
    legend = timeline.build_timeline(items, CLUSTERS)["legend"]
    assert [g["name"] for g in legend] == ["推理", "多模态", "未归类"]


def test_malformed_collected_at_buckets_last():
    items = [
        _item("a", "2026-06-01T00:00:00", cluster=0),
        _item("b", "", cluster=0),
    ]
    out = timeline.build_timeline(items, CLUSTERS)
    assert [m["title"] for m in out["months"]] == ["2026年6月", "未知时间"]


def test_empty_input():
    out = timeline.build_timeline([], CLUSTERS)
    assert out == {"months": [], "stats": {"total": 0, "span": "", "top_galaxy": None}, "legend": []}


from aishelf.db import schema as db_schema

_ITEM_COLS = ["id", "type", "title", "author", "platform", "source_url",
              "published_at", "collected_at", "summary", "keywords",
              "content_hash", "synced_at", "cluster", "hook"]


def _insert(con, *, id, collected_at, type="video", title="t", cluster=None, hook=None):
    vals = {"id": id, "type": type, "title": title, "author": "A", "platform": "p",
            "source_url": "https://x", "published_at": "2026-01-01T00:00:00",
            "collected_at": collected_at, "summary": "s", "keywords": "[]",
            "content_hash": "h", "synced_at": "2026-01-01T00:00:00",
            "cluster": cluster, "hook": hook}
    con.execute(f"INSERT INTO items ({','.join(_ITEM_COLS)}) VALUES "
                f"({','.join('?'*len(_ITEM_COLS))})", [vals[c] for c in _ITEM_COLS])


def _seed(db_path):
    con = db_schema.connect(db_path)
    db_schema.init_db(con)
    con.execute("INSERT INTO clusters (id,name,color,signature) VALUES (0,'推理','#ff9a3c','s0')")
    _insert(con, id="v1", collected_at="2026-06-10T00:00:00", cluster=0, hook="看它")
    _insert(con, id="b1", collected_at="2026-04-01T00:00:00", type="blog", cluster=None)
    con.commit(); con.close()


def test_load_timeline_reads_db(tmp_path):
    db = str(tmp_path / "atlas.db")
    _seed(db)
    out = timeline.load_timeline(db)
    assert out["stats"]["total"] == 2
    assert [m["title"] for m in out["months"]] == ["2026年6月", "2026年4月"]
    assert out["months"][0]["items"][0]["hook"] == "看它"


def test_load_timeline_missing_db_is_empty(tmp_path):
    out = timeline.load_timeline(str(tmp_path / "nope.db"))
    assert out["stats"]["total"] == 0
    assert out["months"] == []


def test_load_timeline_old_db_missing_columns_is_empty(tmp_path):
    db = str(tmp_path / "old.db")
    con = db_schema.connect(db)
    con.execute("CREATE TABLE items (id TEXT)")   # no collected_at/cluster/hook
    con.commit(); con.close()
    out = timeline.load_timeline(db)
    assert out["stats"]["total"] == 0

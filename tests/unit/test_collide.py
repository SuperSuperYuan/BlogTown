import math
import random

import numpy as np

from aishelf.site import collide


def _vec(deg):
    r = math.radians(deg)
    return [math.cos(r), math.sin(r)]


def test_pick_pair_only_in_band():
    # cos(0,66)=0.407 (in [0.30,0.50)); cos(0,8)=0.990 (>=hi, excluded);
    # cos(66,8)=cos58=0.530 (>=hi, excluded) -> only (a,b) qualifies.
    ids = ["a", "b", "c"]
    matrix = np.array([_vec(0), _vec(66), _vec(8)], dtype=np.float32)
    meta = {"a": {"type": "video", "author": "X"},
            "b": {"type": "blog", "author": "Y"},
            "c": {"type": "video", "author": "Z"}}
    assert collide.pick_pair(ids, matrix, meta, rng=random.Random(0)) == ("a", "b")


def test_pick_pair_prefers_cross_type_author():
    # (a,b) in-band same type+author -> score 0; (a,c) in-band cross -> score 2.
    ids = ["a", "b", "c"]
    matrix = np.array([_vec(0), _vec(66), _vec(67)], dtype=np.float32)
    meta = {"a": {"type": "video", "author": "X"},
            "b": {"type": "video", "author": "X"},
            "c": {"type": "blog", "author": "Y"}}
    assert collide.pick_pair(ids, matrix, meta, rng=random.Random(0)) == ("a", "c")


def test_pick_pair_lock_id_restricts_and_orders():
    # lock 'b': only (a,b) is in-band and contains b -> returned with b first.
    ids = ["a", "b", "c"]
    matrix = np.array([_vec(0), _vec(66), _vec(67)], dtype=np.float32)
    meta = {"a": {"type": "video", "author": "X"},
            "b": {"type": "blog", "author": "Y"},
            "c": {"type": "blog", "author": "Z"}}
    assert collide.pick_pair(ids, matrix, meta, lock_id="b", rng=random.Random(0)) == ("b", "a")


def test_pick_pair_none_when_no_band():
    ids = ["a", "b"]
    matrix = np.array([_vec(0), _vec(2)], dtype=np.float32)  # cos2=0.999 too high
    meta = {"a": {"type": "video", "author": "X"}, "b": {"type": "blog", "author": "Y"}}
    assert collide.pick_pair(ids, matrix, meta, rng=random.Random(0)) is None


def test_pick_pair_none_when_too_few():
    matrix = np.array([_vec(0)], dtype=np.float32)
    assert collide.pick_pair(["a"], matrix, {"a": {}}, rng=random.Random(0)) is None


def test_random_pair_two_distinct():
    p = collide.random_pair(["a", "b", "c"], rng=random.Random(0))
    assert p[0] != p[1] and set(p) <= {"a", "b", "c"}


def test_random_pair_honors_lock():
    assert collide.random_pair(["a", "b", "c"], lock_id="a", rng=random.Random(0))[0] == "a"


def test_random_pair_none_when_too_few():
    assert collide.random_pair(["a"], rng=random.Random(0)) is None


import json

from aishelf import embed, alias as _alias
from aishelf.db.sync import sync


def _write_video(data_dir, vid, summary="普通摘要"):
    (data_dir / "videos").mkdir(parents=True, exist_ok=True)
    rec = {"id": vid, "type": "video", "title": f"标题{vid}", "author": "作者甲",
           "platform": "youtube", "source_url": f"https://x/{vid}",
           "published_at": "2024-01-01", "summary": summary, "keywords": [],
           "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}
    (data_dir / "videos" / f"{vid}.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def test_load_pair_space_empty_when_no_embeddings(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: False)
    sync(data, db)
    ids, matrix, meta = collide.load_pair_space(db)
    assert ids == [] and meta == {} and matrix.shape[0] == 0


def test_load_pair_space_groups_embedded(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    _write_video(data, "v2")
    monkeypatch.setattr(embed, "model_name", lambda: "m")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(_alias, "is_configured", lambda: False)
    sync(data, db)
    ids, matrix, meta = collide.load_pair_space(db)
    assert set(ids) == {"v1", "v2"}
    assert matrix.shape == (2, 2)
    assert meta["v1"]["type"] == "video" and meta["v1"]["author"] == "作者甲"


def test_load_pair_space_tolerates_missing_db(tmp_path):
    ids, matrix, meta = collide.load_pair_space(tmp_path / "nope.db")
    assert ids == [] and meta == {}


def test_build_messages_structure():
    msgs = collide.build_messages(
        {"title": "标题A", "summary": "摘要A", "keywords": ["k1"], "author": "作者A", "type": "video"},
        {"title": "标题B", "summary": "摘要B", "keywords": [], "author": "作者B", "type": "blog"},
    )
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    for label in ["【共同的暗线】", "【关键张力】", "【碰撞出的新点子】"]:
        assert label in msgs[0]["content"]
    assert "Markdown" in msgs[0]["content"]
    assert "标题A" in msgs[1]["content"] and "标题B" in msgs[1]["content"]

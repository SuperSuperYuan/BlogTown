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

from types import SimpleNamespace

from aishelf.site import digest as digest_mod


def _it(id, collected_at, type="video", title="T"):
    return SimpleNamespace(id=id, collected_at=collected_at, type=type, title=title)


def test_recent_sorted_by_collected_desc():
    items = [_it("a", "2024-01-01T00:00:00"),
             _it("b", "2024-03-01T00:00:00"),
             _it("c", "2024-02-01T00:00:00")]
    d = digest_mod.build_digest(items, {}, today="2026-06-17", recent_n=2)
    assert [e.item.id for e in d.recent] == ["b", "c"]


def test_recent_n_limit_and_gem_from_older():
    items = [_it(f"i{n}", f"2024-01-{n:02d}T00:00:00") for n in range(1, 8)]  # i1..i7
    d = digest_mod.build_digest(items, {}, today="2026-06-17", recent_n=5)
    recent_ids = {e.item.id for e in d.recent}
    assert len(d.recent) == 5
    assert recent_ids == {"i7", "i6", "i5", "i4", "i3"}
    assert d.gem is not None
    assert d.gem.item.id in {"i2", "i1"}
    assert d.gem.item.id not in recent_ids


def test_gem_deterministic_per_today():
    items = [_it(f"i{n}", f"2024-01-{n:02d}T00:00:00") for n in range(1, 10)]
    a = digest_mod.build_digest(items, {}, today="2026-06-17")
    b = digest_mod.build_digest(items, {}, today="2026-06-17")
    assert a.gem.item.id == b.gem.item.id
    c = digest_mod.build_digest(items, {}, today="2026-06-18")
    assert c.gem.item.id not in {e.item.id for e in c.recent}


def test_gem_rotates_across_days():
    # older pool has 4 items (i4..i1); over many days the seeded pick varies.
    items = [_it(f"i{n}", f"2024-01-{n:02d}T00:00:00") for n in range(1, 10)]
    gems = {digest_mod.build_digest(items, {}, today=f"2026-06-{d:02d}").gem.item.id
            for d in range(1, 29)}
    assert len(gems) > 1   # the gem is seed-dependent and rotates over days


def test_no_gem_when_no_older():
    items = [_it("a", "2024-01-02T00:00:00"), _it("b", "2024-01-01T00:00:00")]
    d = digest_mod.build_digest(items, {}, today="2026-06-17", recent_n=5)
    assert len(d.recent) == 2 and d.gem is None


def test_hooks_attached_with_blank_default():
    items = [_it("a", "2024-01-02T00:00:00"), _it("b", "2024-01-01T00:00:00")]
    d = digest_mod.build_digest(items, {"a": "钩子A"}, today="2026-06-17", recent_n=5)
    by = {e.item.id: e.hook for e in d.recent}
    assert by["a"] == "钩子A" and by["b"] == ""


def test_empty_items():
    d = digest_mod.build_digest([], {}, today="2026-06-17")
    assert d.recent == [] and d.gem is None


def test_unparseable_collected_at_sorts_last():
    items = [_it("good", "2024-05-01T00:00:00"), _it("bad", "not-a-date")]
    d = digest_mod.build_digest(items, {}, today="2026-06-17", recent_n=5)
    assert [e.item.id for e in d.recent] == ["good", "bad"]

from datetime import datetime

from aishelf.site import schedules


def _write(path, text):
    path.write_text(text, encoding="utf-8")


# ---- load_schedules ----

def test_load_parses_entries(tmp_path):
    f = tmp_path / "s.yaml"
    _write(f, """
schedules:
  - name: karpathy
    time: "10:00"
    prompt: 检查新视频
    enabled: true
  - name: blogs
    time: "08:30"
    prompt: 找博客
""")
    out = schedules.load_schedules(f)
    assert [s.name for s in out] == ["karpathy", "blogs"]
    assert (out[0].hour, out[0].minute) == (10, 0)
    assert (out[1].hour, out[1].minute) == (8, 30)
    assert out[1].enabled is True  # default when omitted


def test_load_missing_file_is_empty(tmp_path):
    assert schedules.load_schedules(tmp_path / "nope.yaml") == []


def test_load_skips_malformed_entries(tmp_path):
    f = tmp_path / "s.yaml"
    _write(f, """
schedules:
  - name: ok
    time: "10:00"
    prompt: good
  - name: no-time
    prompt: missing time
  - name: bad-time
    time: "25:99"
    prompt: out of range
  - time: "09:00"
    prompt: no name
  - name: no-prompt
    time: "09:00"
""")
    out = schedules.load_schedules(f)
    assert [s.name for s in out] == ["ok"]


def test_load_dedups_name_keeps_first(tmp_path):
    f = tmp_path / "s.yaml"
    _write(f, """
schedules:
  - name: dup
    time: "10:00"
    prompt: first
  - name: dup
    time: "11:00"
    prompt: second
""")
    out = schedules.load_schedules(f)
    assert len(out) == 1
    assert out[0].prompt == "first"


def test_load_reads_env_path(tmp_path, monkeypatch):
    f = tmp_path / "env.yaml"
    _write(f, 'schedules:\n  - name: e\n    time: "07:00"\n    prompt: p\n')
    monkeypatch.setenv("AISHELF_SCHEDULES", str(f))
    out = schedules.load_schedules()
    assert [s.name for s in out] == ["e"]


# ---- due_schedules (pure) ----

def _sched(name, hour, minute, enabled=True, prompt="p"):
    return schedules.Schedule(name=name, hour=hour, minute=minute, prompt=prompt, enabled=enabled)


def test_due_not_yet_time(tmp_path):
    s = _sched("a", 10, 0)
    now = datetime(2026, 6, 5, 9, 59)
    assert schedules.due_schedules([s], {}, now) == []


def test_due_after_time_not_run_today():
    s = _sched("a", 10, 0)
    now = datetime(2026, 6, 5, 10, 1)
    assert schedules.due_schedules([s], {}, now) == [s]


def test_due_already_run_today():
    s = _sched("a", 10, 0)
    now = datetime(2026, 6, 5, 10, 1)
    state = {"a": "2026-06-05"}
    assert schedules.due_schedules([s], state, now) == []


def test_due_disabled_never_runs():
    s = _sched("a", 10, 0, enabled=False)
    now = datetime(2026, 6, 5, 23, 0)
    assert schedules.due_schedules([s], {}, now) == []


def test_due_catch_up_after_overnight():
    # last ran yesterday; site only woke at 11:00 today -> should catch up
    s = _sched("a", 10, 0)
    now = datetime(2026, 6, 5, 11, 0)
    state = {"a": "2026-06-04"}
    assert schedules.due_schedules([s], state, now) == [s]


def test_due_mixed():
    a = _sched("a", 8, 0)            # past, not run -> due
    b = _sched("b", 23, 0)          # future -> not due
    c = _sched("c", 9, 0, enabled=False)  # disabled -> not due
    now = datetime(2026, 6, 5, 10, 0)
    assert schedules.due_schedules([a, b, c], {}, now) == [a]

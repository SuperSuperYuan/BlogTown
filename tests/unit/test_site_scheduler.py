from datetime import datetime

import pytest

from aishelf.site import collect, schedule_state, scheduler, schedules


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    return tmp_path


def _sched(name, hour, prompt="p"):
    return schedules.Schedule(name=name, hour=hour, minute=0, prompt=prompt, enabled=True)


def test_run_due_now_runs_due_and_records_state(data_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(schedules, "load_schedules", lambda: [_sched("a", 8, "pa"), _sched("b", 23, "pb")])
    monkeypatch.setattr(collect, "run_once", lambda prompt, data_dir=None: calls.append(prompt) or "ok")

    ran = scheduler.run_due_now(now=datetime(2026, 6, 5, 10, 0))

    assert ran == ["a"]           # b is at 23:00, not yet due
    assert calls == ["pa"]
    assert schedule_state.load_state(data_dir) == {"a": "2026-06-05"}


def test_run_due_now_skips_already_run(data_dir, monkeypatch):
    schedule_state.save_state(data_dir, {"a": "2026-06-05"})
    monkeypatch.setattr(schedules, "load_schedules", lambda: [_sched("a", 8)])
    monkeypatch.setattr(collect, "run_once", lambda prompt, data_dir=None: pytest.fail("must not run"))

    ran = scheduler.run_due_now(now=datetime(2026, 6, 5, 10, 0))
    assert ran == []


def test_run_due_now_failure_does_not_record_or_block_others(data_dir, monkeypatch):
    monkeypatch.setattr(schedules, "load_schedules", lambda: [_sched("a", 8, "boom"), _sched("b", 8, "fine")])

    def fake_run(prompt, data_dir=None):
        if prompt == "boom":
            raise RuntimeError("hermes down")
        return "ok"

    monkeypatch.setattr(collect, "run_once", fake_run)

    ran = scheduler.run_due_now(now=datetime(2026, 6, 5, 10, 0))

    assert ran == ["b"]                         # b still ran despite a failing
    state = schedule_state.load_state(data_dir)
    assert "a" not in state                      # failed run is not recorded -> retried next tick
    assert state["b"] == "2026-06-05"


def test_run_due_now_syncs_db_after_collection(monkeypatch, tmp_path):
    from datetime import datetime

    from aishelf.site import scheduler, schedules, schedule_state

    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        schedules, "load_schedules",
        lambda: [schedules.Schedule(name="s1", hour=10, minute=0, prompt="p", enabled=True)],
    )
    monkeypatch.setattr(schedule_state, "load_state", lambda d: {})
    monkeypatch.setattr(schedule_state, "save_state", lambda d, s: None)
    monkeypatch.setattr(scheduler.collect, "run_once", lambda prompt: "ok")

    called = {}
    monkeypatch.setattr(
        scheduler.db_sync, "sync",
        lambda data_dir, db_path: called.setdefault("args", (data_dir, db_path)),
    )

    ran = scheduler.run_due_now(now=datetime(2024, 1, 1, 10, 0))
    assert ran == ["s1"]
    assert "args" in called  # sync was triggered after the run


def test_run_due_now_no_sync_when_nothing_ran(monkeypatch, tmp_path):
    from datetime import datetime

    from aishelf.site import scheduler, schedules, schedule_state

    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(schedules, "load_schedules", lambda: [])
    monkeypatch.setattr(schedule_state, "load_state", lambda d: {})

    called = {}
    monkeypatch.setattr(scheduler.db_sync, "sync", lambda *a, **k: called.setdefault("hit", True))
    ran = scheduler.run_due_now(now=datetime(2024, 1, 1, 10, 0))
    assert ran == []
    assert "hit" not in called

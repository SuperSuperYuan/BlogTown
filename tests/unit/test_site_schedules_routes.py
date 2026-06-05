import pytest
from fastapi.testclient import TestClient

TOKEN = "test-token"
AUTH = {"X-Collect-Token": TOKEN}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    allow = tmp_path / "allow.txt"
    allow.write_text(f"{TOKEN}\n", encoding="utf-8")
    monkeypatch.setenv("AISHELF_COLLECT_ALLOWLIST", str(allow))
    sched = tmp_path / "schedules.yaml"
    monkeypatch.setenv("AISHELF_SCHEDULES", str(sched))
    from aishelf.site.app import app
    return TestClient(app), sched


def _seed(sched, *items):
    from aishelf.site import schedules
    schedules.save_schedules(list(items), sched)


def _S(name, hour=10, minute=0, prompt="p", enabled=True):
    from aishelf.site import schedules
    return schedules.Schedule(name=name, hour=hour, minute=minute, prompt=prompt, enabled=enabled)


# ---- display (folded into /collect) ----

def test_collect_page_shows_schedule_section(client):
    c, sched = client
    _seed(sched, _S("karpathy", 10, 0, "检查新视频"))
    r = c.get("/collect")
    assert r.status_code == 200
    assert "定时" in r.text
    assert "karpathy" in r.text and "检查新视频" in r.text


def test_collect_page_empty_state(client):
    c, _ = client
    r = c.get("/collect")
    assert r.status_code == 200
    assert "暂无定时任务" in r.text


# ---- add / upsert ----

def test_add_requires_token(client):
    c, _ = client
    r = c.post("/schedules", json={"name": "a", "time": "10:00", "prompt": "p"})
    assert r.status_code == 403


def test_add_persists(client):
    c, sched = client
    from aishelf.site import schedules
    r = c.post("/schedules", json={"name": "a", "time": "10:00", "prompt": "检查", "enabled": True}, headers=AUTH)
    assert r.status_code == 200
    out = schedules.load_schedules(sched)
    assert [s.name for s in out] == ["a"]
    assert out[0].hour == 10 and out[0].prompt == "检查"


def test_add_upserts_by_name(client):
    c, sched = client
    from aishelf.site import schedules
    c.post("/schedules", json={"name": "a", "time": "10:00", "prompt": "first"}, headers=AUTH)
    c.post("/schedules", json={"name": "a", "time": "11:30", "prompt": "second"}, headers=AUTH)
    out = schedules.load_schedules(sched)
    assert len(out) == 1
    assert (out[0].hour, out[0].minute, out[0].prompt) == (11, 30, "second")


def test_add_bad_time_400(client):
    c, _ = client
    r = c.post("/schedules", json={"name": "a", "time": "25:00", "prompt": "p"}, headers=AUTH)
    assert r.status_code == 400


def test_add_bad_name_400(client):
    c, _ = client
    r = c.post("/schedules", json={"name": "a/b", "time": "10:00", "prompt": "p"}, headers=AUTH)
    assert r.status_code == 400


def test_add_empty_prompt_400(client):
    c, _ = client
    r = c.post("/schedules", json={"name": "a", "time": "10:00", "prompt": "   "}, headers=AUTH)
    assert r.status_code == 400


# ---- toggle ----

def test_toggle_flips_enabled(client):
    c, sched = client
    from aishelf.site import schedules
    _seed(sched, _S("a", enabled=True))
    r = c.post("/schedules/a/toggle", headers=AUTH)
    assert r.status_code == 200
    assert schedules.load_schedules(sched)[0].enabled is False


def test_toggle_requires_token(client):
    c, sched = client
    _seed(sched, _S("a"))
    r = c.post("/schedules/a/toggle")
    assert r.status_code == 403


def test_toggle_unknown_404(client):
    c, _ = client
    r = c.post("/schedules/nope/toggle", headers=AUTH)
    assert r.status_code == 404


# ---- delete ----

def test_delete_removes(client):
    c, sched = client
    from aishelf.site import schedules
    _seed(sched, _S("a"), _S("b", 8, 0, "q"))
    r = c.post("/schedules/a/delete", headers=AUTH)
    assert r.status_code == 200
    assert [s.name for s in schedules.load_schedules(sched)] == ["b"]


def test_delete_requires_token(client):
    c, sched = client
    _seed(sched, _S("a"))
    r = c.post("/schedules/a/delete")
    assert r.status_code == 403


def test_delete_unknown_404(client):
    c, _ = client
    r = c.post("/schedules/nope/delete", headers=AUTH)
    assert r.status_code == 404

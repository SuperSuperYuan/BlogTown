import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aishelf.db import schema as db_schema
from aishelf.db.config import default_db_path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"

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


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    return data


@pytest.fixture
def client(data_dir):
    from aishelf.site.app import app
    return TestClient(app)


def test_timeline_populated(data_dir, client):
    db = default_db_path(str(data_dir))
    Path(db).unlink(missing_ok=True)   # ignore any stale DB copied from fixtures
    db = str(db)
    con = db_schema.connect(db)
    db_schema.init_db(con)
    con.execute("INSERT INTO clusters (id,name,color,signature) VALUES (0,'推理','#ff9a3c','s0')")
    _insert(con, id="vid-x", collected_at="2026-06-10T00:00:00", cluster=0, hook="必看")
    con.commit(); con.close()

    r = client.get("/timeline")
    assert r.status_code == 200
    assert "收藏编年史" in r.text
    assert "2026年6月" in r.text
    assert "/videos/vid-x" in r.text
    assert "必看" in r.text


def test_timeline_empty_state(client, monkeypatch, tmp_path):
    # point at a data dir with no DB
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("AISHELF_DATA_DIR", str(empty))
    r = client.get("/timeline")
    assert r.status_code == 200
    assert "还没有收藏" in r.text


def test_topbar_has_timeline_link(client):
    r = client.get("/timeline")
    assert 'href="/timeline"' in r.text

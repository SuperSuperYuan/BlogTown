import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aishelf.db import schema as db_schema
from aishelf.db.config import default_db_path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"

_ITEM_COLS = ["id", "type", "title", "author", "platform", "source_url",
              "published_at", "collected_at", "summary", "keywords",
              "content_hash", "synced_at", "embedding", "hook"]


def _insert(con, *, id, type="video", title="t", hook=None, embedding=b"x"):
    vals = {"id": id, "type": type, "title": title, "author": "A", "platform": "p",
            "source_url": "https://x", "published_at": "2026-01-01T00:00:00",
            "collected_at": "2026-01-01T00:00:00", "summary": "s", "keywords": "[]",
            "content_hash": "h", "synced_at": "2026-01-01T00:00:00",
            "embedding": embedding, "hook": hook}
    con.execute(f"INSERT INTO items ({','.join(_ITEM_COLS)}) VALUES "
                f"({','.join('?'*len(_ITEM_COLS))})", [vals[c] for c in _ITEM_COLS])


def _edge(con, a, b, w=0.7):
    s, d = (a, b) if a < b else (b, a)
    con.execute("INSERT INTO edges (src,dst,weight) VALUES (?,?,?)", (s, d, w))


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


def test_islands_populated(data_dir, client):
    db = default_db_path(str(data_dir))
    Path(db).unlink(missing_ok=True)   # ignore any stale DB copied from fixtures
    db = str(db)
    con = db_schema.connect(db)
    db_schema.init_db(con)
    _insert(con, id="lone-x", title="孤独之书", hook="独一无二")
    _insert(con, id="p", title="P")
    _insert(con, id="q", title="Q")
    _edge(con, "p", "q")
    con.commit(); con.close()

    r = client.get("/islands")
    assert r.status_code == 200
    assert "孤本" in r.text
    assert "孤独之书" in r.text
    assert "/videos/lone-x" in r.text
    assert "/videos/q" in r.text          # q shown as p's neighbor link


def test_islands_no_embeddings_state(client, monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("AISHELF_DATA_DIR", str(empty))
    r = client.get("/islands")
    assert r.status_code == 200
    assert "ATLAS_EMBED" in r.text


def test_topbar_has_islands_link(client):
    assert 'href="/islands"' in client.get("/islands").text

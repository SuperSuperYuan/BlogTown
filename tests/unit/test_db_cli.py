import json

from aishelf.db import schema
from aishelf.db.__main__ import main


def _write_video(data_dir, item_id):
    d = data_dir / "videos"
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        "id": item_id, "type": "video", "title": "标题", "author": "作者甲",
        "platform": "youtube", "source_url": f"https://x/{item_id}",
        "published_at": "2024-01-01", "summary": "摘要", "keywords": [],
        "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg",
    }
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def test_cli_sync_populates_db(tmp_path, monkeypatch, capsys):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    monkeypatch.setenv("AISHELF_DB_PATH", str(db))
    rc = main(["sync"])
    assert rc == 0
    con = schema.connect(db)
    assert con.execute("SELECT count(*) FROM items").fetchone()[0] == 1
    assert "+1" in capsys.readouterr().out


def test_cli_rebuild_drops_first(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    monkeypatch.setenv("AISHELF_DB_PATH", str(db))
    main(["sync"])
    (data / "videos" / "v1.json").unlink()  # remove source
    _write_video(data, "v2")
    rc = main(["sync", "--rebuild"])
    assert rc == 0
    con = schema.connect(db)
    ids = {r[0] for r in con.execute("SELECT id FROM items")}
    assert ids == {"v2"}

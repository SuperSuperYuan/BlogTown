import json

import pytest

from aishelf.site import items


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    (tmp_path / "videos").mkdir()
    (tmp_path / "blogs").mkdir()
    (tmp_path / "notes").mkdir()
    return tmp_path


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_delete_removes_record_and_note(data_dir):
    rec = data_dir / "videos" / "youtube-x.json"
    note = data_dir / "notes" / "youtube-x.json"
    _write(rec, {"id": "youtube-x"})
    _write(note, {"id": "youtube-x", "text": "n"})
    assert items.delete_item("youtube-x") is True
    assert not rec.exists()
    assert not note.exists()


def test_delete_blog_record(data_dir):
    rec = data_dir / "blogs" / "blog-y.json"
    _write(rec, {"id": "blog-y"})
    assert items.delete_item("blog-y") is True
    assert not rec.exists()


def test_delete_unknown_returns_false(data_dir):
    assert items.delete_item("nope-z") is False


def test_delete_no_record_keeps_orphan_note(data_dir):
    # a lingering note with no content record must NOT be destroyed by a no-op delete
    note = data_dir / "notes" / "orphan-x.json"
    _write(note, {"id": "orphan-x", "text": "keep me"})
    assert items.delete_item("orphan-x") is False
    assert note.exists()


def test_delete_record_without_note_ok(data_dir):
    rec = data_dir / "videos" / "youtube-x.json"
    _write(rec, {"id": "youtube-x"})
    assert items.delete_item("youtube-x") is True  # missing note is not an error
    assert not rec.exists()


@pytest.mark.parametrize("bad", ["../etc", "a/b", "..", "x\\y", "", "a b", "a..b"])
def test_bad_id_rejected(data_dir, bad):
    with pytest.raises(ValueError):
        items.safe_id(bad)
    with pytest.raises(ValueError):
        items.delete_item(bad)

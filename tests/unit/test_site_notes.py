import json

import pytest

from aishelf.site import notes


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    return tmp_path


def test_save_then_load_roundtrip(data_dir):
    notes.save_note("youtube-abc", "hello\nworld")
    assert notes.load_note("youtube-abc") == "hello\nworld"


def test_load_missing_returns_empty(data_dir):
    assert notes.load_note("nope-xyz") == ""


def test_save_writes_json_with_fields(data_dir):
    notes.save_note("youtube-abc", "hi", now=lambda: "2026-01-01T00:00:00")
    obj = json.loads((data_dir / "notes" / "youtube-abc.json").read_text(encoding="utf-8"))
    assert obj == {"id": "youtube-abc", "text": "hi", "updated_at": "2026-01-01T00:00:00"}


def test_empty_text_clears_note(data_dir):
    notes.save_note("youtube-abc", "something")
    notes.save_note("youtube-abc", "")
    assert notes.load_note("youtube-abc") == ""


@pytest.mark.parametrize("bad", ["../etc", "a/b", "..", "x\\y", "", "a b", "a..b"])
def test_unsafe_id_rejected(data_dir, bad):
    with pytest.raises(ValueError):
        notes.save_note(bad, "x")
    with pytest.raises(ValueError):
        notes.load_note(bad)

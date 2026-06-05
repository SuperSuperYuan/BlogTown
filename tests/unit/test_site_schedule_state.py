from aishelf.site import schedule_state


def test_round_trip(tmp_path):
    schedule_state.save_state(tmp_path, {"a": "2026-06-05", "b": "2026-06-04"})
    assert schedule_state.load_state(tmp_path) == {"a": "2026-06-05", "b": "2026-06-04"}


def test_load_missing_is_empty(tmp_path):
    assert schedule_state.load_state(tmp_path) == {}


def test_load_corrupt_json_is_empty(tmp_path):
    (tmp_path / "schedule_state.json").write_text("{not json", encoding="utf-8")
    assert schedule_state.load_state(tmp_path) == {}


def test_save_is_atomic_no_tmp_left(tmp_path):
    schedule_state.save_state(tmp_path, {"a": "2026-06-05"})
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []
    assert (tmp_path / "schedule_state.json").exists()


def test_save_creates_data_dir(tmp_path):
    nested = tmp_path / "fresh"
    schedule_state.save_state(nested, {"a": "2026-06-05"})
    assert schedule_state.load_state(nested) == {"a": "2026-06-05"}

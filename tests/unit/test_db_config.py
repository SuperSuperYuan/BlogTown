from pathlib import Path

from aishelf.db.config import default_db_path


def test_default_db_path_is_under_data_dir(tmp_path):
    assert default_db_path(tmp_path) == tmp_path / "atlas.db"


def test_default_db_path_accepts_str(tmp_path):
    assert default_db_path(str(tmp_path)) == Path(str(tmp_path)) / "atlas.db"


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DB_PATH", "/somewhere/custom.db")
    assert default_db_path(tmp_path) == Path("/somewhere/custom.db")

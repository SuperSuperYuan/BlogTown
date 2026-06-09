"""Where the derived SQLite database lives."""

from __future__ import annotations

import os
from pathlib import Path


def default_db_path(data_dir) -> Path:
    """Path to the derived SQLite DB.

    `AISHELF_DB_PATH` overrides; otherwise `<data_dir>/atlas.db`.
    """
    override = os.environ.get("AISHELF_DB_PATH")
    if override:
        return Path(override)
    return Path(data_dir) / "atlas.db"

"""Where the display site reads collected content from."""

from __future__ import annotations

import os
from pathlib import Path


def get_data_dir() -> Path:
    """Directory holding `videos/` and `blogs/` record files."""
    return Path(os.environ.get("AISHELF_DATA_DIR", "data"))

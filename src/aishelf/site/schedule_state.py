"""Persisted last-run dates for scheduled collection.

`schedule_state.json` maps a schedule name to the ISO date it last ran, so the
scheduler knows whether today's run already happened (across restarts). Written
atomically, like notes, so a crash never leaves a half-written state file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILE = "schedule_state.json"


def _state_path(data_dir) -> Path:
    return Path(data_dir) / _STATE_FILE


def load_state(data_dir) -> dict[str, str]:
    """Return {name: last-run ISO date}; a missing/corrupt file yields {}."""
    try:
        data = json.loads(_state_path(data_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("unreadable schedule state: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_state(data_dir, state: dict[str, str]) -> None:
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / _STATE_FILE
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix="schedule_state.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, final)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

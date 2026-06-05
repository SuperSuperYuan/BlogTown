"""Per-item user notes, stored separately from Hermes-collected records."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from aishelf.site.config import get_data_dir

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def notes_dir() -> Path:
    return get_data_dir() / "notes"


def _safe_id(item_id: str) -> str:
    if not item_id or ".." in item_id or "/" in item_id or "\\" in item_id or not _SAFE_ID.match(item_id):
        raise ValueError(f"unsafe note id: {item_id!r}")
    return item_id


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_note(item_id: str) -> str:
    _safe_id(item_id)
    path = notes_dir() / f"{item_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("text", "")
    except FileNotFoundError:
        return ""
    except (json.JSONDecodeError, OSError) as exc:
        # don't silently destroy a corrupted note on the next save
        logger.warning("unreadable note %s: %s", path, exc)
        return ""


def save_note(item_id: str, text: str, now=_now) -> str:
    _safe_id(item_id)
    directory = notes_dir()
    directory.mkdir(parents=True, exist_ok=True)
    updated_at = now()
    payload = {"id": item_id, "text": text, "updated_at": updated_at}
    final = directory / f"{item_id}.json"
    # Unique temp file + atomic rename: concurrent POSTs to the same id can't
    # corrupt a shared temp, and a failed write leaves nothing behind.
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f"{item_id}.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, final)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return updated_at

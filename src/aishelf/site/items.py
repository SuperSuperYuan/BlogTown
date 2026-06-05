"""Content items: id validation and deletion (record + note)."""

from __future__ import annotations

import re

from aishelf.site.config import get_data_dir

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
# Mirrors the modality dirs read by contract.loader; keep the two in sync.
_MODALITY_DIRS = ("videos", "blogs")


def safe_id(item_id: str) -> str:
    """Validate a content item id; raise ValueError on anything path-unsafe."""
    if not item_id or ".." in item_id or "/" in item_id or "\\" in item_id or not _SAFE_ID.match(item_id):
        raise ValueError(f"unsafe item id: {item_id!r}")
    return item_id


def delete_item(item_id: str) -> bool:
    """Delete the content record (video or blog) and its note.

    Returns True if a content record was removed, False if none existed.
    A missing note is not an error.
    """
    safe_id(item_id)
    base = get_data_dir()
    removed_record = False
    for sub in _MODALITY_DIRS:
        try:
            (base / sub / f"{item_id}.json").unlink()  # race-free vs exists()+unlink
            removed_record = True
        except FileNotFoundError:
            pass
    (base / "notes" / f"{item_id}.json").unlink(missing_ok=True)
    return removed_record

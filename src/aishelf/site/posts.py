"""Create, read, and update self-authored blog posts.

A post is an ordinary BlogItem JSON record in data/blogs/<id>.json with
origin="self" and a markdown `body`. Writes are atomic (.tmp + os.replace),
mirroring notes.py. This module performs pure persistence — the route layer
triggers the off-thread DB re-sync (same split as save_note).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from aishelf.contract.models import BlogItem
from aishelf.site.config import blog_author, get_data_dir
from aishelf.site.items import safe_id

logger = logging.getLogger(__name__)

SUMMARY_LEN = 120


def blogs_dir() -> Path:
    return get_data_dir() / "blogs"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# Strip the common inline markdown markers so the auto-summary reads as prose.
_MD_NOISE = re.compile(r"[#>*_`~\[\]()!-]+")


def _summarize(body: str, limit: int = SUMMARY_LEN) -> str:
    """First ~`limit` chars of `body` with markdown markers/whitespace stripped."""
    text = _MD_NOISE.sub(" ", body or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _new_id(title: str, timestamp: str) -> str:
    digest = hashlib.sha1((title + timestamp).encode("utf-8")).hexdigest()[:12]
    return safe_id(f"post-{digest}")


def _write(item: BlogItem) -> None:
    """Atomic write of a BlogItem to data/blogs/<id>.json."""
    directory = blogs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{item.id}.json"
    payload = item.model_dump(mode="json")
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f"{item.id}.", suffix=".json.tmp")
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


def create_post(title: str, body: str, now=_now) -> BlogItem:
    """Create a self-authored post, persist it, and return the record."""
    timestamp = now()
    item = BlogItem(
        id=_new_id(title, timestamp),
        title=title,
        author=blog_author(),
        platform="atlas",
        source_url="",
        published_at=timestamp,
        collected_at=timestamp,
        summary=_summarize(body),
        keywords=[],
        body=body,
        origin="self",
    )
    _write(item)
    return item


def read_post(item_id: str) -> BlogItem | None:
    """Load a self-authored post by id, or None if missing/not self/unreadable."""
    try:
        safe_id(item_id)
    except ValueError:
        return None
    path = blogs_dir() / f"{item_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        item = BlogItem(**data)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
        logger.warning("unreadable post %s: %s", path, exc)
        return None
    return item if item.origin == "self" else None


def update_post(item_id: str, title: str, body: str) -> BlogItem:
    """Update an existing self-authored post, preserving published_at.

    Raises LookupError if no self-authored post with that id exists.
    """
    existing = read_post(item_id)
    if existing is None:
        raise LookupError(item_id)
    updated = existing.model_copy(update={
        "title": title,
        "body": body,
        "summary": _summarize(body),
    })
    _write(updated)
    return updated

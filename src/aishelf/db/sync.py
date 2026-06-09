"""Sync the JSON contract files into the derived SQLite DB (idempotent).

Full-scan upsert by id + prune of rows whose files vanished, all in one
transaction. The contract loader is reused so malformed records are skipped.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aishelf.contract.loader import load_items
from aishelf.db import schema, tokenize
from aishelf.db.config import default_db_path

logger = logging.getLogger(__name__)


@dataclass
class SyncSummary:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0


_COLUMNS = (
    "id", "type", "title", "author", "author_id", "platform", "source_url",
    "published_at", "collected_at", "summary", "keywords",
    "thumbnail_url", "duration_seconds", "embed_url",
    "cover_image_url", "site_name", "content_hash", "synced_at",
)


def _note_text(data_dir, item_id: str) -> str:
    """The user's note for an item, or '' if none/unreadable. Read by data_dir
    (not the env) so sync stays self-contained on its argument."""
    path = Path(data_dir) / "notes" / f"{item_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("text", "")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""


def _content_hash(item, note: str = "") -> str:
    blob = json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1((blob + "\x00" + note).encode("utf-8")).hexdigest()


def _row(item, content_hash: str, synced_at: str) -> dict:
    d = item.model_dump(mode="json")
    return {
        "id": d["id"], "type": d["type"], "title": d["title"],
        "author": d["author"], "author_id": d.get("author_id"),
        "platform": d["platform"], "source_url": d["source_url"],
        "published_at": d["published_at"], "collected_at": d["collected_at"],
        "summary": d["summary"],
        "keywords": json.dumps(d["keywords"], ensure_ascii=False),
        "thumbnail_url": d.get("thumbnail_url"),
        "duration_seconds": d.get("duration_seconds"),
        "embed_url": d.get("embed_url"),
        "cover_image_url": d.get("cover_image_url"),
        "site_name": d.get("site_name"),
        "content_hash": content_hash, "synced_at": synced_at,
    }


def sync(data_dir, db_path=None) -> SyncSummary:
    """Mirror `data_dir/{videos,blogs}` into the SQLite DB. Returns a summary."""
    db_path = db_path or default_db_path(data_dir)
    items = load_items(data_dir)
    con = schema.connect(db_path)
    try:
        schema.init_db(con)
        summary = SyncSummary()
        existing = {
            r["id"]: r["content_hash"]
            for r in con.execute("SELECT id, content_hash FROM items")
        }
        synced_at = datetime.now(timezone.utc).isoformat()
        seen: set[str] = set()

        placeholders = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS if c != "id")
        upsert_sql = (
            f"INSERT INTO items ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}"
        )

        for it in items:
            seen.add(it.id)
            note = _note_text(data_dir, it.id)
            h = _content_hash(it, note)
            if existing.get(it.id) == h:
                summary.unchanged += 1
                continue
            con.execute(upsert_sql, _row(it, h, synced_at))
            con.execute("DELETE FROM items_fts WHERE item_id = ?", (it.id,))
            con.execute(
                "INSERT INTO items_fts (item_id, title, summary, keywords, author, note) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    it.id,
                    tokenize.bigrams(it.title),
                    tokenize.bigrams(it.summary),
                    tokenize.bigrams(" ".join(it.keywords)),
                    tokenize.bigrams(it.author),
                    tokenize.bigrams(note),
                ),
            )
            if it.id in existing:
                summary.updated += 1
            else:
                summary.added += 1

        stale = [i for i in existing if i not in seen]
        for rid in stale:
            con.execute("DELETE FROM items WHERE id = ?", (rid,))
            con.execute("DELETE FROM items_fts WHERE item_id = ?", (rid,))
        summary.removed = len(stale)

        con.commit()
        return summary
    finally:
        con.close()

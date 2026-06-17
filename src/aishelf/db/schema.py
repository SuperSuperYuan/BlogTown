"""SQLite schema for the derived content index + FTS5 full-text table.

`items` is a flat table mirroring the contract (modality-specific columns are
nullable). `items_fts` is a standalone FTS5 table holding bigram-segmented text
(maintained by sync, not triggers, because segmentation happens in Python).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
  id            TEXT PRIMARY KEY,
  type          TEXT NOT NULL,
  title         TEXT NOT NULL,
  author        TEXT NOT NULL,
  author_id     TEXT,
  platform      TEXT NOT NULL,
  source_url    TEXT NOT NULL,
  published_at  TEXT NOT NULL,
  collected_at  TEXT NOT NULL,
  summary       TEXT NOT NULL,
  keywords      TEXT NOT NULL,
  thumbnail_url     TEXT,
  duration_seconds  INTEGER,
  embed_url         TEXT,
  cover_image_url   TEXT,
  site_name         TEXT,
  embedding         BLOB,
  embedding_model   TEXT,
  embedding_dim     INTEGER,
  alias             TEXT,
  hook              TEXT,
  content_hash  TEXT NOT NULL,
  synced_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_type      ON items(type);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  item_id UNINDEXED,
  title, summary, keywords, author, note,
  tokenize='unicode61'
);
CREATE TABLE IF NOT EXISTS edges (
  src    TEXT NOT NULL,
  dst    TEXT NOT NULL,
  weight REAL NOT NULL,
  PRIMARY KEY (src, dst)
);
"""


def connect(db_path) -> sqlite3.Connection:
    """Open a connection (creating parent dirs), with WAL + Row factory."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def init_db(con: sqlite3.Connection) -> None:
    """Create tables/FTS if absent (idempotent)."""
    con.executescript(SCHEMA_SQL)
    con.commit()

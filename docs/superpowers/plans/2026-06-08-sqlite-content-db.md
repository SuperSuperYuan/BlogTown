# SQLite 派生内容库 + 全文检索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Hermes 采集到的 JSON 内容派生进本地 SQLite，提供中文全文检索，作为后续消费功能的基础。

**Architecture:** DB 是文件契约的派生视图（文件仍是唯一真相，可全量重建）。新增 `aishelf/db/` 子包，分层 `site → db → contract`。中文检索用 bigram 预分词 + FTS5 `unicode61`（无新依赖）。同步在每次采集后触发，外加手动 CLI 兜底。新增只读 `/api/search` 作为首个消费功能。

**Tech Stack:** Python 标准库 `sqlite3`（FTS5/unicode61，已验证本机 SQLite 3.51.2 支持）、Pydantic v2 契约模型、FastAPI、pytest。无新增依赖。

**约定（沿用现有代码风格）:**
- 源码在 `src/aishelf/`，包名 `aishelf`。测试在 `tests/unit/`，纯离线。
- 运行单测：`pytest tests/unit/test_xxx.py::test_name -v`。
- 验证假设已完成：FTS5+unicode61 可用；bigram 方案命中 2 字/多字 CJK + ASCII；search SQL 用 **FTS 表名**（非别名）做 `MATCH`/`bm25`。

---

## File Structure

**新建（`aishelf/db/` 子包，每个文件单一职责）:**
- `src/aishelf/db/__init__.py` — 空包标记。
- `src/aishelf/db/config.py` — DB 路径解析（`default_db_path`）。
- `src/aishelf/db/schema.py` — DDL 常量 + `connect()` + `init_db()`。
- `src/aishelf/db/tokenize.py` — 纯函数 `bigrams()` + `to_match_query()`。
- `src/aishelf/db/sync.py` — `sync()` 全量扫描 + upsert + prune。
- `src/aishelf/db/search.py` — `search()` FTS5 检索。
- `src/aishelf/db/__main__.py` — CLI `python -m aishelf.db sync [--rebuild]`。

**修改:**
- `src/aishelf/site/scheduler.py` — 定时采集后触发 sync。
- `src/aishelf/site/app.py` — chat 采集后台 sync + `/api/search` 路由。
- `CLAUDE.md` — 模块清单 / Config / Commands。

**新建测试:**
- `tests/unit/test_db_config.py`, `test_db_schema.py`, `test_db_tokenize.py`,
  `test_db_sync.py`, `test_db_search.py`, `test_db_cli.py`, `test_site_search_api.py`
- 修改 `tests/unit/test_site_scheduler.py`、`tests/unit/test_site_collect_routes.py`

---

## Task 1: db 包骨架 + 配置（`config.py`）

**Files:**
- Create: `src/aishelf/db/__init__.py`
- Create: `src/aishelf/db/config.py`
- Test: `tests/unit/test_db_config.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_db_config.py
from pathlib import Path

from aishelf.db.config import default_db_path


def test_default_db_path_is_under_data_dir(tmp_path):
    assert default_db_path(tmp_path) == tmp_path / "atlas.db"


def test_default_db_path_accepts_str(tmp_path):
    assert default_db_path(str(tmp_path)) == Path(str(tmp_path)) / "atlas.db"


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DB_PATH", "/somewhere/custom.db")
    assert default_db_path(tmp_path) == Path("/somewhere/custom.db")
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_db_config.py -v`
Expected: FAIL（`ModuleNotFoundError: aishelf.db`）

- [ ] **Step 3: 实现**

```python
# src/aishelf/db/__init__.py
```
(空文件)

```python
# src/aishelf/db/config.py
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_db_config.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add src/aishelf/db/__init__.py src/aishelf/db/config.py tests/unit/test_db_config.py
git commit -m "feat(db): db package skeleton + db path config"
```

---

## Task 2: Schema + 连接（`schema.py`）

**Files:**
- Create: `src/aishelf/db/schema.py`
- Test: `tests/unit/test_db_schema.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_db_schema.py
from aishelf.db import schema


def _tables(con):
    rows = con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()
    return {r[0] for r in rows}


def test_init_db_creates_items_and_fts(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    names = _tables(con)
    assert "items" in names
    assert "items_fts" in names


def test_init_db_is_idempotent(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    schema.init_db(con)  # second call must not raise
    assert "items" in _tables(con)


def test_connect_creates_parent_dirs(tmp_path):
    nested = tmp_path / "a" / "b" / "atlas.db"
    con = schema.connect(nested)
    schema.init_db(con)
    assert nested.exists()


def test_fts_matches_after_insert(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    con.execute(
        "INSERT INTO items_fts (item_id, title, summary, keywords, author) "
        "VALUES ('x', '语言 模型', 's', 'k', 'a')"
    )
    rows = con.execute("SELECT item_id FROM items_fts WHERE items_fts MATCH '\"语言\"'").fetchall()
    assert [r[0] for r in rows] == ["x"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_db_schema.py -v`
Expected: FAIL（`ImportError: cannot import name 'schema'` 或 `connect` 未定义）

- [ ] **Step 3: 实现**

```python
# src/aishelf/db/schema.py
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
  content_hash  TEXT NOT NULL,
  synced_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_type      ON items(type);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  item_id UNINDEXED,
  title, summary, keywords, author,
  tokenize='unicode61'
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_db_schema.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add src/aishelf/db/schema.py tests/unit/test_db_schema.py
git commit -m "feat(db): sqlite schema (items + items_fts) and connection helper"
```

---

## Task 3: 中文分词（`tokenize.py`）

**Files:**
- Create: `src/aishelf/db/tokenize.py`
- Test: `tests/unit/test_db_tokenize.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_db_tokenize.py
from aishelf.db.tokenize import bigrams, to_match_query


def test_bigrams_cjk_multichar():
    assert bigrams("大语言模型") == "大语 语言 言模 模型"


def test_bigrams_cjk_two_char():
    assert bigrams("检索") == "检索"


def test_bigrams_single_cjk_char():
    assert bigrams("中") == "中"


def test_bigrams_ascii_lowercased_and_whole():
    assert bigrams("RAG Transformer") == "rag transformer"


def test_bigrams_mixed():
    assert bigrams("RAG 检索增强") == "rag 检索 索增 增强"


def test_bigrams_strips_punctuation_and_empty():
    assert bigrams("！！！") == ""
    assert bigrams("") == ""


def test_to_match_query_two_char():
    assert to_match_query("检索") == '"检索"'


def test_to_match_query_multichar_is_anded():
    assert to_match_query("大模型") == '"大模" AND "模型"'


def test_to_match_query_empty_when_no_tokens():
    assert to_match_query("   ") == ""
    assert to_match_query("！") == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_db_tokenize.py -v`
Expected: FAIL（模块/函数未定义）

- [ ] **Step 3: 实现**

```python
# src/aishelf/db/tokenize.py
"""CJK-aware tokenization for FTS5 full-text indexing and querying.

Text is stored/queried as bigrams: ASCII/digit runs kept whole (lowercased),
CJK runs split into overlapping 2-grams (a lone CJK char kept as-is). This lets
SQLite's plain unicode61 tokenizer match 2-character Chinese terms, which the
built-in trigram tokenizer cannot.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")


def _segment(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text or ""):
        if tok[0].isascii():
            out.append(tok.lower())
        elif len(tok) == 1:
            out.append(tok)
        else:
            out.extend(tok[i : i + 2] for i in range(len(tok) - 1))
    return out


def bigrams(text: str) -> str:
    """Space-joined bigram tokens for indexing."""
    return " ".join(_segment(text))


def to_match_query(user_q: str) -> str:
    """Build an FTS5 MATCH expression: AND of quoted bigrams. Empty if no tokens."""
    toks = _segment(user_q)
    if not toks:
        return ""
    return " AND ".join(f'"{t}"' for t in toks)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_db_tokenize.py -v`
Expected: PASS（9 passed）

- [ ] **Step 5: 提交**

```bash
git add src/aishelf/db/tokenize.py tests/unit/test_db_tokenize.py
git commit -m "feat(db): bigram tokenizer for CJK full-text"
```

---

## Task 4: 同步（`sync.py`）

**Files:**
- Create: `src/aishelf/db/sync.py`
- Test: `tests/unit/test_db_sync.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_db_sync.py
import json

from aishelf.db import schema
from aishelf.db.sync import sync


def _write(data_dir, sub, item_id, **over):
    rec = {
        "id": item_id,
        "type": "video" if sub == "videos" else "blog",
        "title": over.get("title", "标题"),
        "author": over.get("author", "作者甲"),
        "platform": "youtube" if sub == "videos" else "blog",
        "source_url": f"https://x/{item_id}",
        "published_at": over.get("published_at", "2024-01-01"),
        "summary": over.get("summary", "摘要"),
        "keywords": over.get("keywords", ["关键词"]),
        "collected_at": "2024-01-02T00:00:00",
    }
    if sub == "videos":
        rec["thumbnail_url"] = f"https://img/{item_id}.jpg"
    d = data_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _rows(db_path):
    con = schema.connect(db_path)
    return {r["id"]: r for r in con.execute("SELECT * FROM items")}


def test_sync_inserts_rows_and_fts(tmp_path):
    data = tmp_path / "data"
    db = tmp_path / "atlas.db"
    _write(data, "videos", "v1", title="大语言模型")
    _write(data, "blogs", "b1")
    summary = sync(data, db)
    assert (summary.added, summary.updated, summary.removed, summary.unchanged) == (2, 0, 0, 0)
    rows = _rows(db)
    assert set(rows) == {"v1", "b1"}
    assert rows["v1"]["keywords"] == json.dumps(["关键词"], ensure_ascii=False)
    con = schema.connect(db)
    fts = con.execute("SELECT item_id FROM items_fts WHERE items_fts MATCH '\"语言\"'").fetchall()
    assert [r[0] for r in fts] == ["v1"]


def test_sync_unchanged_skips_on_second_run(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1")
    sync(data, db)
    summary = sync(data, db)
    assert (summary.added, summary.updated, summary.unchanged) == (0, 0, 1)


def test_sync_updates_changed_record(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1", title="旧标题")
    sync(data, db)
    _write(data, "videos", "v1", title="新标题")
    summary = sync(data, db)
    assert (summary.added, summary.updated) == (0, 1)
    assert _rows(db)["v1"]["title"] == "新标题"


def test_sync_prunes_deleted_file(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1")
    _write(data, "videos", "v2")
    sync(data, db)
    (data / "videos" / "v1.json").unlink()
    summary = sync(data, db)
    assert summary.removed == 1
    assert set(_rows(db)) == {"v2"}
    con = schema.connect(db)
    assert con.execute("SELECT count(*) FROM items_fts WHERE item_id='v1'").fetchone()[0] == 0


def test_sync_skips_malformed(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1")
    (data / "videos" / "bad.json").write_text("{not json", encoding="utf-8")
    summary = sync(data, db)
    assert summary.added == 1
    assert set(_rows(db)) == {"v1"}
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_db_sync.py -v`
Expected: FAIL（`sync` 未定义）

- [ ] **Step 3: 实现**

```python
# src/aishelf/db/sync.py
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


def _content_hash(item) -> str:
    blob = json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


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
            h = _content_hash(it)
            if existing.get(it.id) == h:
                summary.unchanged += 1
                continue
            con.execute(upsert_sql, _row(it, h, synced_at))
            con.execute("DELETE FROM items_fts WHERE item_id = ?", (it.id,))
            con.execute(
                "INSERT INTO items_fts (item_id, title, summary, keywords, author) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    it.id,
                    tokenize.bigrams(it.title),
                    tokenize.bigrams(it.summary),
                    tokenize.bigrams(" ".join(it.keywords)),
                    tokenize.bigrams(it.author),
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
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_db_sync.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add src/aishelf/db/sync.py tests/unit/test_db_sync.py
git commit -m "feat(db): idempotent file->sqlite sync with upsert + prune"
```

---

## Task 5: 检索（`search.py`）

**Files:**
- Create: `src/aishelf/db/search.py`
- Test: `tests/unit/test_db_search.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_db_search.py
import json

from aishelf.db.search import search
from aishelf.db.sync import sync


def _write(data_dir, sub, item_id, title, summary="摘要", keywords=None):
    rec = {
        "id": item_id,
        "type": "video" if sub == "videos" else "blog",
        "title": title, "author": "作者甲",
        "platform": "youtube" if sub == "videos" else "blog",
        "source_url": f"https://x/{item_id}",
        "published_at": "2024-01-01", "summary": summary,
        "keywords": keywords or [], "collected_at": "2024-01-02T00:00:00",
    }
    if sub == "videos":
        rec["thumbnail_url"] = f"https://img/{item_id}.jpg"
    d = data_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _seed(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1", "大语言模型与检索增强生成 RAG")
    _write(data, "blogs", "b1", "短视频推荐系统")
    sync(data, db)
    return db


def test_search_cjk_two_char(tmp_path):
    db = _seed(tmp_path)
    hits = search(db, "检索")
    assert [h.id for h in hits] == ["v1"]


def test_search_cjk_multichar(tmp_path):
    db = _seed(tmp_path)
    assert [h.id for h in search(db, "大语言模型")] == ["v1"]


def test_search_ascii_case_insensitive(tmp_path):
    db = _seed(tmp_path)
    assert [h.id for h in search(db, "rag")] == ["v1"]


def test_search_type_filter(tmp_path):
    db = _seed(tmp_path)
    assert search(db, "视频", type="video") == []
    assert [h.id for h in search(db, "视频", type="blog")] == ["b1"]


def test_search_empty_query_returns_empty(tmp_path):
    db = _seed(tmp_path)
    assert search(db, "") == []
    assert search(db, "   ") == []


def test_search_no_match_returns_empty(tmp_path):
    db = _seed(tmp_path)
    assert search(db, "量子计算") == []


def test_search_hit_carries_structured_fields(tmp_path):
    db = _seed(tmp_path)
    hit = search(db, "检索")[0]
    assert hit.type == "video"
    assert hit.author == "作者甲"
    assert isinstance(hit.keywords, list)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_db_search.py -v`
Expected: FAIL（`search` 未定义）

- [ ] **Step 3: 实现**

```python
# src/aishelf/db/search.py
"""Full-text search over the derived DB (the consumption layer).

Bigram-encodes the query, runs an FTS5 MATCH ranked by bm25, and rehydrates
the structured row from `items`. Uses the FTS table name (not an alias) for
MATCH/bm25 — required by FTS5.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from aishelf.db import schema, tokenize


@dataclass
class SearchHit:
    id: str
    type: str
    title: str
    author: str
    platform: str
    source_url: str
    published_at: str
    summary: str
    keywords: list[str]


def _hit(row) -> SearchHit:
    return SearchHit(
        id=row["id"], type=row["type"], title=row["title"], author=row["author"],
        platform=row["platform"], source_url=row["source_url"],
        published_at=row["published_at"], summary=row["summary"],
        keywords=json.loads(row["keywords"]),
    )


def search(db_path, q, *, type=None, limit: int = 20, offset: int = 0) -> list[SearchHit]:
    """Ranked full-text hits. Empty query (no tokens) -> []."""
    match = tokenize.to_match_query(q)
    if not match:
        return []
    con = schema.connect(db_path)
    try:
        schema.init_db(con)
        sql = (
            "SELECT i.* FROM items_fts JOIN items i ON i.id = items_fts.item_id "
            "WHERE items_fts MATCH :match"
        )
        params: dict = {"match": match}
        if type is not None:
            sql += " AND i.type = :type"
            params["type"] = type
        sql += " ORDER BY bm25(items_fts) LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset
        return [_hit(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_db_search.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add src/aishelf/db/search.py tests/unit/test_db_search.py
git commit -m "feat(db): FTS5 full-text search returning structured hits"
```

---

## Task 6: CLI（`__main__.py`）

**Files:**
- Create: `src/aishelf/db/__main__.py`
- Test: `tests/unit/test_db_cli.py`

注：CLI 直接从 `os.environ` 读 `AISHELF_DATA_DIR`（默认 `data`），不 import `aishelf.site`，以保持 `db → contract` 单向依赖。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_db_cli.py
import json

from aishelf.db import schema
from aishelf.db.__main__ import main


def _write_video(data_dir, item_id):
    d = data_dir / "videos"
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        "id": item_id, "type": "video", "title": "标题", "author": "作者甲",
        "platform": "youtube", "source_url": f"https://x/{item_id}",
        "published_at": "2024-01-01", "summary": "摘要", "keywords": [],
        "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg",
    }
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def test_cli_sync_populates_db(tmp_path, monkeypatch, capsys):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    monkeypatch.setenv("AISHELF_DB_PATH", str(db))
    rc = main(["sync"])
    assert rc == 0
    con = schema.connect(db)
    assert con.execute("SELECT count(*) FROM items").fetchone()[0] == 1
    assert "+1" in capsys.readouterr().out


def test_cli_rebuild_drops_first(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    monkeypatch.setenv("AISHELF_DB_PATH", str(db))
    main(["sync"])
    (data / "videos" / "v1.json").unlink()  # remove source
    _write_video(data, "v2")
    rc = main(["sync", "--rebuild"])
    assert rc == 0
    con = schema.connect(db)
    ids = {r[0] for r in con.execute("SELECT id FROM items")}
    assert ids == {"v2"}
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_db_cli.py -v`
Expected: FAIL（`main` 未定义 / 模块无 main）

- [ ] **Step 3: 实现**

```python
# src/aishelf/db/__main__.py
"""CLI for the derived DB: `python -m aishelf.db sync [--rebuild]`.

Reads AISHELF_DATA_DIR / AISHELF_DB_PATH from the environment so the db
package stays free of any aishelf.site import.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from aishelf.db import schema
from aishelf.db import sync as sync_mod
from aishelf.db.config import default_db_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aishelf.db")
    sub = parser.add_subparsers(dest="command", required=True)
    p_sync = sub.add_parser("sync", help="Sync data files into the SQLite DB")
    p_sync.add_argument("--rebuild", action="store_true", help="Drop and recreate tables first")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    data_dir = Path(os.environ.get("AISHELF_DATA_DIR", "data"))
    db_path = default_db_path(data_dir)

    if args.command == "sync":
        if args.rebuild:
            con = schema.connect(db_path)
            con.executescript("DROP TABLE IF EXISTS items; DROP TABLE IF EXISTS items_fts;")
            con.commit()
            con.close()
        s = sync_mod.sync(data_dir, db_path)
        print(f"synced: +{s.added} ~{s.updated} -{s.removed} ={s.unchanged}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_db_cli.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add src/aishelf/db/__main__.py tests/unit/test_db_cli.py
git commit -m "feat(db): CLI 'python -m aishelf.db sync [--rebuild]' for backfill/rebuild"
```

---

## Task 7: 定时采集后触发同步（`scheduler.py`）

**Files:**
- Modify: `src/aishelf/site/scheduler.py`
- Test: `tests/unit/test_site_scheduler.py`（追加用例）

- [ ] **Step 1: 写失败测试（追加到现有文件末尾）**

```python
# tests/unit/test_site_scheduler.py  (append)
def test_run_due_now_syncs_db_after_collection(monkeypatch, tmp_path):
    from datetime import datetime

    from aishelf.site import scheduler, schedules, schedule_state

    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        schedules, "load_schedules",
        lambda: [schedules.Schedule(name="s1", hour=10, minute=0, prompt="p", enabled=True)],
    )
    monkeypatch.setattr(schedule_state, "load_state", lambda d: {})
    monkeypatch.setattr(schedule_state, "save_state", lambda d, s: None)
    monkeypatch.setattr(scheduler.collect, "run_once", lambda prompt: "ok")

    called = {}
    monkeypatch.setattr(
        scheduler.db_sync, "sync",
        lambda data_dir, db_path: called.setdefault("args", (data_dir, db_path)),
    )

    ran = scheduler.run_due_now(now=datetime(2024, 1, 1, 10, 0))
    assert ran == ["s1"]
    assert "args" in called  # sync was triggered after the run


def test_run_due_now_no_sync_when_nothing_ran(monkeypatch, tmp_path):
    from datetime import datetime

    from aishelf.site import scheduler, schedules, schedule_state

    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(schedules, "load_schedules", lambda: [])
    monkeypatch.setattr(schedule_state, "load_state", lambda d: {})

    called = {}
    monkeypatch.setattr(scheduler.db_sync, "sync", lambda *a, **k: called.setdefault("hit", True))
    ran = scheduler.run_due_now(now=datetime(2024, 1, 1, 10, 0))
    assert ran == []
    assert "hit" not in called
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_site_scheduler.py -k sync -v`
Expected: FAIL（`scheduler.db_sync` 不存在 → AttributeError）

- [ ] **Step 3: 实现（修改 `scheduler.py`）**

在 import 区追加（紧随现有 `from aishelf.site.config import get_data_dir` 之后）：

```python
from aishelf.db import sync as db_sync
from aishelf.db.config import default_db_path
```

在 `run_due_now` 的 `return ran` 之前插入：

```python
    if ran:
        try:
            summary = db_sync.sync(data_dir, default_db_path(data_dir))
            logger.info("DB synced after scheduled collection: %s", summary)
        except Exception as exc:  # derived DB; failure is recoverable, never fatal
            logger.warning("DB sync after scheduled collection failed: %s", exc)
    return ran
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_site_scheduler.py -v`
Expected: PASS（含原有用例 + 2 新增）

- [ ] **Step 5: 提交**

```bash
git add src/aishelf/site/scheduler.py tests/unit/test_site_scheduler.py
git commit -m "feat(site): sync DB after each scheduled collection"
```

---

## Task 8: 手动 chat 采集后后台同步（`app.py`）

**Files:**
- Modify: `src/aishelf/site/app.py`（`collect_chat` 路由）
- Test: `tests/unit/test_site_collect_routes.py`（追加用例）

- [ ] **Step 1: 写失败测试（追加）**

```python
# tests/unit/test_site_collect_routes.py  (append)
def test_collect_chat_triggers_db_sync(client, monkeypatch):
    import threading

    from aishelf.site import hermes
    from aishelf.db import sync as db_sync

    monkeypatch.setattr(hermes, "get_client", lambda: _FakeClient([_chunk("written")]))

    done = threading.Event()
    monkeypatch.setattr(db_sync, "sync", lambda data_dir, db_path: done.set())

    r = client.post(
        "/collect/chat",
        json={"messages": [{"role": "user", "content": "爬视频"}]},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert "written" in r.text  # stream fully consumed
    assert done.wait(timeout=5)  # background sync ran after the stream
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_site_collect_routes.py::test_collect_chat_triggers_db_sync -v`
Expected: FAIL（`done.wait` 超时返回 False → 断言失败）

- [ ] **Step 3: 实现（修改 `app.py` 的 `collect_chat`）**

把现有 `collect_chat` 函数体的 return 部分替换为带后台同步的包装：

```python
@app.post("/collect/chat")
def collect_chat(req: _ChatRequest, x_collect_token: str | None = Header(default=None)):
    # Gate the expensive collection path: only allowlisted tokens may proceed.
    _require_collect_token(x_collect_token)
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    data_dir = get_data_dir()
    system = {"role": "system", "content": collect.build_collection_instructions(data_dir)}
    payload = [system] + [m.model_dump() for m in req.messages]
    stream = hermes.stream_chat(payload)

    def _with_sync():
        try:
            yield from stream
        finally:
            # Hermes wrote files during the turn; refresh the derived DB off-thread
            # so it never blocks or breaks the SSE response.
            def _bg():
                try:
                    db_sync.sync(data_dir, default_db_path(data_dir))
                except Exception as exc:  # derived DB; recoverable
                    logger.warning("DB sync after chat collection failed: %s", exc)
            threading.Thread(target=_bg, name="aishelf-chat-sync", daemon=True).start()

    return StreamingResponse(_with_sync(), media_type="text/event-stream")
```

在 `app.py` import 区追加（与其它 `from aishelf...` 同处）：

```python
from aishelf.db import search as db_search
from aishelf.db import sync as db_sync
from aishelf.db.config import default_db_path
```

（`threading` 已在 app.py 顶部导入；`db_search` 供 Task 9 使用，这里一并加入。）

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_site_collect_routes.py -v`
Expected: PASS（含原有用例 + 新增）

- [ ] **Step 5: 提交**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_collect_routes.py
git commit -m "feat(site): sync DB in background after manual chat collection"
```

---

## Task 9: 只读检索 API（`/api/search`）

**Files:**
- Modify: `src/aishelf/site/app.py`（新增路由 + `asdict` 导入）
- Test: `tests/unit/test_site_search_api.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/test_site_search_api.py
import json

import pytest
from fastapi.testclient import TestClient


def _write(data_dir, sub, item_id, title):
    rec = {
        "id": item_id, "type": "video" if sub == "videos" else "blog",
        "title": title, "author": "作者甲",
        "platform": "youtube" if sub == "videos" else "blog",
        "source_url": f"https://x/{item_id}", "published_at": "2024-01-01",
        "summary": "摘要", "keywords": [], "collected_at": "2024-01-02T00:00:00",
    }
    if sub == "videos":
        rec["thumbnail_url"] = "https://img/x.jpg"
    d = data_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    _write(tmp_path, "videos", "v1", "大语言模型与检索增强")
    _write(tmp_path, "blogs", "b1", "短视频推荐系统")
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")
    from aishelf.site.app import app
    return TestClient(app)


def test_api_search_cjk(client):
    r = client.get("/api/search", params={"q": "检索"})
    assert r.status_code == 200
    body = r.json()
    assert [h["id"] for h in body["results"]] == ["v1"]


def test_api_search_type_filter(client):
    r = client.get("/api/search", params={"q": "视频", "type": "blog"})
    assert [h["id"] for h in r.json()["results"]] == ["b1"]


def test_api_search_empty_query(client):
    r = client.get("/api/search", params={"q": ""})
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_api_search_bad_type_400(client):
    r = client.get("/api/search", params={"q": "x", "type": "podcast"})
    assert r.status_code == 400
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/unit/test_site_search_api.py -v`
Expected: FAIL（404 — 路由不存在）

- [ ] **Step 3: 实现（修改 `app.py`）**

把 `from dataclasses import replace` 改为：

```python
from dataclasses import asdict, replace
```

在常量区（`HOME_PREVIEW = 8` 之后）加：

```python
SEARCH_API_PER_PAGE = 20
```

在文件末尾（其它路由之后）新增路由：

```python
@app.get("/api/search")
def api_search(q: str = "", type: str | None = None, page: int = 1):
    """Read-only full-text search over the derived DB (first consumption feature)."""
    if type not in (None, "video", "blog"):
        raise HTTPException(status_code=400, detail="type 只能是 video 或 blog")
    data_dir = get_data_dir()
    offset = max(0, page - 1) * SEARCH_API_PER_PAGE
    hits = db_search.search(
        default_db_path(data_dir), q, type=type, limit=SEARCH_API_PER_PAGE, offset=offset
    )
    return {"q": q, "type": type, "page": page, "results": [asdict(h) for h in hits]}
```

（`db_search` 与 `default_db_path` 已在 Task 8 导入。）

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/unit/test_site_search_api.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_search_api.py
git commit -m "feat(site): read-only /api/search endpoint over the derived DB"
```

---

## Task 10: 文档（`CLAUDE.md`）

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 模块清单加 db 包**

在 Architecture 的源码列表里 `aishelf/site/` 段之后追加：

```markdown
- `aishelf/db/` — derived SQLite index of the contract files: `config.py`
  (`default_db_path`), `schema.py` (`items` + FTS5 `items_fts`, `connect`,
  `init_db`), `tokenize.py` (CJK bigram `bigrams`/`to_match_query`), `sync.py`
  (idempotent `sync` — upsert + prune), `search.py` (`search` over FTS5),
  `__main__.py` (CLI). The DB is a rebuildable view; files stay source of truth.
```

- [ ] **Step 2: Commands 段加 sync 命令**

在 Commands 列表里加：

```markdown
- Backfill/rebuild the derived DB: `python -m aishelf.db sync` (`--rebuild` to drop+recreate)
```

- [ ] **Step 3: Config 段加 env**

在 Config 列表的 `AISHELF_DATA_DIR` 项之后加：

```markdown
- `AISHELF_DB_PATH` — derived SQLite DB file (default `<data_dir>/atlas.db`).
```

- [ ] **Step 4: 加一段说明（Data & storage 段末尾）**

```markdown
**Derived DB** (`aishelf.db`): a SQLite file (`<data_dir>/atlas.db`, gitignored)
holding a structured mirror of the contract records plus a bigram FTS5 index for
CJK full-text search. It is a **derived view** — files remain the source of
truth and the DB is rebuildable at any time (`python -m aishelf.db sync`). It is
synced after each collection (scheduled runs and, off-thread, after manual chat
collection). The read-only `GET /api/search?q=&type=&page=` endpoint queries it;
existing browse/search pages still read files. Initial deployment must run one
`python -m aishelf.db sync` to backfill existing records (no startup/periodic
sync by design).
```

- [ ] **Step 5: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: document derived SQLite DB, /api/search, and sync command"
```

---

## Task 11: 全量回归 + 回填验证

- [ ] **Step 1: 跑全部测试**

Run: `pytest`
Expected: 全绿（network 用例默认跳过）。

- [ ] **Step 2: 真实回填现有数据并冒烟**

```bash
python -m aishelf.db sync
```
Expected: 打印 `synced: +N ...`（N≈现有 videos+blogs 文件数），`data/atlas.db` 生成。

```bash
# 站点已在 :8001 运行；验证检索端点（中文）
curl -s 'http://127.0.0.1:8001/api/search?q=模型' | python -m json.tool | head -30
```
Expected: 返回 JSON，`results` 含命中条目（若现有语料含相关词）。

- [ ] **Step 3: 确认 atlas.db 不入库**

Run: `git status --porcelain data/atlas.db`
Expected: 无输出（`data/` 已 gitignore）。

---

## Self-Review 结果

- **Spec 覆盖:** ①模块边界→T1-2;②schema→T2;②分词→T3;③同步→T4;④触发(定时/chat/CLI)→T7/T8/T6;⑤检索→T5;⑥/api/search→T9;⑦config/docs→T10;错误处理→T4/T7/T8 的 try/except + T2 WAL；测试→各 Task 的 TDD 用例。无遗漏。
- **占位符:** 无 TBD/TODO；每个代码步骤含完整代码。
- **类型一致性:** `default_db_path`、`connect/init_db`、`bigrams/to_match_query`、`sync()->SyncSummary`、`search()->list[SearchHit]`、`SyncSummary(added/updated/removed/unchanged)`、`SearchHit` 字段在各 Task 间一致；`scheduler.db_sync`/`app.db_sync`/`app.db_search` 别名引用一致。
- **依赖层次:** `db` 仅依赖 `contract`+stdlib（CLI 用 `os.environ` 而非 import site）；`site` 依赖 `db`。单向无环。

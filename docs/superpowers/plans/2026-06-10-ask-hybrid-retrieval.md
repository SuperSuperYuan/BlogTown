# Ask Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add semantic (vector) retrieval to `/ask`, fused with the existing FTS5 path — vector-primary cosine rerank with FTS5 as an exact-term safety net, degrading gracefully to today's pure-FTS5 behavior when no embedding service is configured/reachable.

**Architecture:** A self-hosted, OpenAI-compatible embedding service (`ATLAS_EMBED_*`, no default → silently disabled when unset) produces vectors. They are stored as BLOBs in the derived `atlas.db` (`db.sync` computes them incrementally; `--rebuild` recomputes all) and searched with brute-force numpy cosine — no vector DB. `ask.retrieve()` unions vector + FTS5 candidates and re-ranks by cosine, flooring weak hits but always keeping FTS5 exact hits. Files stay the source of truth; embeddings are part of the rebuildable derived view.

**Tech Stack:** Python 3.11+, SQLite + FTS5 (stdlib), `openai` SDK (embeddings endpoint), `numpy` (new dep, cosine only), FastAPI/pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-ask-hybrid-retrieval-design.md`

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add `numpy` to `dependencies`. |
| `src/aishelf/embed.py` | Create | OpenAI-compatible embedding client (`ATLAS_EMBED_*`); returns `None` on unconfigured/error. |
| `src/aishelf/db/schema.py` | Modify | Add `embedding`/`embedding_model`/`embedding_dim` columns to `items`. |
| `src/aishelf/db/vector.py` | Create | Pure vector math: `pack`/`unpack`, `load_embeddings`, `cosine_search`. |
| `src/aishelf/db/search.py` | Modify | Add `get_by_ids(db_path, ids)` row hydrator. |
| `src/aishelf/db/sync.py` | Modify | Compute + store embeddings incrementally for new/changed/model-mismatched rows. |
| `src/aishelf/site/ask.py` | Modify | Hybrid `retrieve()` + extracted FTS-only fallback + constants + `_sources_for_ids`. |
| `CLAUDE.md`, `docs/ARCHITECTURE.md` | Modify | Document `ATLAS_EMBED_*`, the hybrid path, and the `sync --rebuild` backfill. |
| `tests/unit/test_embed.py` | Create | Embedding client tests (mocked). |
| `tests/unit/test_db_vector.py` | Create | Vector math tests. |
| `tests/unit/test_db_search.py` | Modify (or create) | `get_by_ids` test. |
| `tests/unit/test_db_sync.py` | Modify | Embedding-storage tests. |
| `tests/unit/test_site_ask.py` | Modify | Hybrid retrieve tests. |

---

## Task 1: Add the numpy dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add numpy to dependencies**

In `pyproject.toml`, change the `dependencies` list to include numpy (append after `jinja2`):

```toml
dependencies = [
  "yt-dlp>=2024.0.0",
  "youtube-transcript-api>=0.6.0",
  "openai>=1.0.0",
  "httpx>=0.27.0",
  "PyYAML>=6.0",
  "pydantic>=2.0",
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
  "jinja2>=3.1",
  "numpy>=1.26",
]
```

- [ ] **Step 2: Install it**

Run: `pip install -e ".[dev]"`
Expected: completes; `python -c "import numpy; print(numpy.__version__)"` prints a version.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add numpy dependency for vector cosine search"
```

---

## Task 2: Embedding client (`aishelf/embed.py`)

**Files:**
- Create: `src/aishelf/embed.py`
- Test: `tests/unit/test_embed.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_embed.py`:

```python
from aishelf import embed


class _FakeEmbeddings:
    def __init__(self, vectors):
        self._vectors = vectors

    def create(self, *, model, input):
        # Mirror the OpenAI SDK shape: resp.data[i].embedding
        class _D:
            def __init__(self, v):
                self.embedding = v
        class _Resp:
            def __init__(self, vs):
                self.data = [_D(v) for v in vs]
        assert isinstance(input, list)
        return _Resp(self._vectors[: len(input)])


class _FakeClient:
    def __init__(self, vectors):
        self.embeddings = _FakeEmbeddings(vectors)


def _configure(monkeypatch):
    monkeypatch.setenv("ATLAS_EMBED_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("ATLAS_EMBED_API_KEY", "k")
    monkeypatch.setenv("ATLAS_EMBED_MODEL", "fake-embed")


def test_not_configured_returns_none(monkeypatch):
    monkeypatch.delenv("ATLAS_EMBED_BASE_URL", raising=False)
    monkeypatch.delenv("ATLAS_EMBED_MODEL", raising=False)
    assert embed.is_configured() is False
    assert embed.model_name() is None
    assert embed.embed_texts(["x"]) is None
    assert embed.embed_query("x") is None


def test_embed_texts_returns_vectors(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(embed, "get_client", lambda s: _FakeClient([[1.0, 2.0], [3.0, 4.0]]))
    assert embed.is_configured() is True
    assert embed.model_name() == "fake-embed"
    assert embed.embed_texts(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]


def test_embed_query_unwraps_single(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(embed, "get_client", lambda s: _FakeClient([[5.0, 6.0]]))
    assert embed.embed_query("hi") == [5.0, 6.0]


def test_empty_input_returns_none(monkeypatch):
    _configure(monkeypatch)
    assert embed.embed_texts([]) is None
    assert embed.embed_query("") is None


def test_client_error_returns_none(monkeypatch):
    _configure(monkeypatch)

    def _boom(s):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(embed, "get_client", _boom)
    assert embed.embed_texts(["a"]) is None
    assert embed.embed_query("a") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_embed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aishelf.embed'`

- [ ] **Step 3: Write the implementation**

Create `src/aishelf/embed.py`:

```python
"""Embedding client for semantic retrieval (self-hosted, OpenAI-compatible).

Reads ATLAS_EMBED_* with NO fallback to the chat/Hermes connection — the chat
provider (e.g. DeepSeek) does not serve embeddings. Unset ⇒ the feature is
disabled and every call returns None, so callers degrade to pure FTS5. Any
client/HTTP error is swallowed to None for the same reason (reads never crash).
"""

from __future__ import annotations

import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)


def get_embed_settings() -> dict[str, str] | None:
    base = os.environ.get("ATLAS_EMBED_BASE_URL")
    model = os.environ.get("ATLAS_EMBED_MODEL")
    if not base or not model:
        return None
    return {"base_url": base, "api_key": os.environ.get("ATLAS_EMBED_API_KEY", ""), "model": model}


def is_configured() -> bool:
    return get_embed_settings() is not None


def model_name() -> str | None:
    s = get_embed_settings()
    return s["model"] if s else None


def get_client(settings: dict[str, str]) -> OpenAI:
    return OpenAI(base_url=settings["base_url"], api_key=settings["api_key"] or "none", timeout=60.0)


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embeddings for a batch, or None if unconfigured / empty / on any error."""
    s = get_embed_settings()
    if s is None or not texts:
        return None
    try:
        client = get_client(s)
        resp = client.embeddings.create(model=s["model"], input=texts)
        return [d.embedding for d in resp.data]
    except Exception as exc:  # degrade to FTS5, never crash a read/sync
        logger.warning("embedding request failed: %s", exc)
        return None


def embed_query(text: str) -> list[float] | None:
    """Single-text convenience wrapper; None when unconfigured/empty/on error."""
    if not text:
        return None
    vecs = embed_texts([text])
    return vecs[0] if vecs else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_embed.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/embed.py tests/unit/test_embed.py
git commit -m "feat(embed): OpenAI-compatible embedding client (ATLAS_EMBED_*, disabled when unset)"
```

---

## Task 3: Add embedding columns to the schema

**Files:**
- Modify: `src/aishelf/db/schema.py:13-41`
- Test: `tests/unit/test_db_vector.py` (covers it indirectly in Task 4); a direct check here

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_db_vector.py` with a schema check (more tests added in Task 4):

```python
from aishelf.db import schema


def test_items_table_has_embedding_columns(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
    con.close()
    assert {"embedding", "embedding_model", "embedding_dim"} <= cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_db_vector.py::test_items_table_has_embedding_columns -v`
Expected: FAIL — the three columns are absent.

- [ ] **Step 3: Add the columns**

In `src/aishelf/db/schema.py`, edit the `items` table in `SCHEMA_SQL` — add three nullable columns just before `content_hash`:

```python
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
"""
```

Note: existing deployments must run `python -m aishelf.db sync --rebuild` once (the `IF NOT EXISTS` will not add columns to a pre-existing table) — documented in Task 8.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_db_vector.py::test_items_table_has_embedding_columns -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/schema.py tests/unit/test_db_vector.py
git commit -m "feat(db): add embedding/embedding_model/embedding_dim columns to items"
```

---

## Task 4: Vector math (`aishelf/db/vector.py`)

**Files:**
- Create: `src/aishelf/db/vector.py`
- Test: `tests/unit/test_db_vector.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_db_vector.py`:

```python
import numpy as np

from aishelf.db import schema, vector


def test_pack_unpack_roundtrip():
    blob = vector.pack([1.0, 2.5, -3.0])
    out = vector.unpack(blob)
    assert isinstance(out, np.ndarray)
    assert out.dtype == np.float32
    assert list(out) == [1.0, 2.5, -3.0]


def _seed(db_path, rows):
    # rows: list of (id, type, vec or None)
    con = schema.connect(db_path)
    schema.init_db(con)
    for rid, typ, vec in rows:
        con.execute(
            "INSERT INTO items (id, type, title, author, platform, source_url, "
            "published_at, collected_at, summary, keywords, embedding, embedding_model, "
            "embedding_dim, content_hash, synced_at) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, typ, "t", "a", "p", "u", "2024-01-01", "2024-01-02", "s", "[]",
             vector.pack(vec) if vec else None, "m" if vec else None,
             len(vec) if vec else None, "h", "2024-01-02"),
        )
    con.commit()
    con.close()


def test_load_embeddings_filters_by_dim_and_nulls(tmp_path):
    db = tmp_path / "atlas.db"
    _seed(db, [
        ("a", "video", [1.0, 0.0]),
        ("b", "blog", [0.0, 1.0]),
        ("c", "video", None),          # no embedding -> excluded
        ("d", "video", [1.0, 0.0, 0.0]),  # wrong dim -> excluded
    ])
    ids, mat = vector.load_embeddings(db, 2)
    assert set(ids) == {"a", "b"}
    assert mat.shape == (2, 2)


def test_load_embeddings_type_filter(tmp_path):
    db = tmp_path / "atlas.db"
    _seed(db, [("a", "video", [1.0, 0.0]), ("b", "blog", [0.0, 1.0])])
    ids, _ = vector.load_embeddings(db, 2, type="video")
    assert ids == ["a"]


def test_cosine_search_orders_by_similarity():
    ids = ["a", "b", "c"]
    mat = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32)
    out = vector.cosine_search([1.0, 0.0], ids, mat, top_n=2)
    assert [i for i, _ in out] == ["a", "b"]
    assert out[0][1] > out[1][1]


def test_cosine_search_empty():
    out = vector.cosine_search([1.0, 0.0], [], np.empty((0, 2), dtype=np.float32), top_n=5)
    assert out == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_db_vector.py -v`
Expected: FAIL — `vector` module / functions undefined (the schema test still passes).

- [ ] **Step 3: Write the implementation**

Create `src/aishelf/db/vector.py`:

```python
"""Pure vector storage + brute-force cosine search over the derived DB.

Embeddings are stored as float32 BLOBs in items.embedding. At a personal-library
scale (hundreds–low-thousands of rows) exhaustive cosine in numpy is sub-100 ms,
so there is no vector index. load_embeddings only returns rows whose dim matches
the query, sidestepping any cross-model dimension mismatch.
"""

from __future__ import annotations

import numpy as np

from aishelf.db import schema


def pack(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def unpack(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def load_embeddings(db_path, dim: int, *, type=None) -> tuple[list[str], np.ndarray]:
    """ids + an (N, dim) matrix for rows that have an embedding of this dim."""
    con = schema.connect(db_path)
    try:
        schema.init_db(con)
        sql = ("SELECT id, embedding FROM items "
               "WHERE embedding IS NOT NULL AND embedding_dim = :dim")
        params: dict = {"dim": dim}
        if type is not None:
            sql += " AND type = :type"
            params["type"] = type
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    if not rows:
        return [], np.empty((0, dim), dtype=np.float32)
    ids = [r["id"] for r in rows]
    mat = np.stack([unpack(r["embedding"]) for r in rows])
    return ids, mat


def cosine_search(query_vec, ids: list[str], matrix: np.ndarray, *, top_n: int) -> list[tuple[str, float]]:
    """(id, cosine) pairs, highest similarity first, capped at top_n."""
    if not ids:
        return []
    q = np.asarray(query_vec, dtype=np.float32)
    qn = float(np.linalg.norm(q))
    if qn == 0.0:
        return []
    norms = np.linalg.norm(matrix, axis=1)
    sims = (matrix @ q) / (norms * qn + 1e-12)
    order = np.argsort(-sims)[:top_n]
    return [(ids[i], float(sims[i])) for i in order]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_db_vector.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/vector.py tests/unit/test_db_vector.py
git commit -m "feat(db): vector pack/unpack + load_embeddings + cosine_search"
```

---

## Task 5: Hydrate items by id (`db.search.get_by_ids`)

**Files:**
- Modify: `src/aishelf/db/search.py`
- Test: `tests/unit/test_db_search.py`

- [ ] **Step 1: Write the failing test**

Create (or append to) `tests/unit/test_db_search.py`:

```python
from aishelf.db import schema, search


def _seed(db_path):
    con = schema.connect(db_path)
    schema.init_db(con)
    for rid in ("a", "b"):
        con.execute(
            "INSERT INTO items (id, type, title, author, platform, source_url, "
            "published_at, collected_at, summary, keywords, content_hash, synced_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, "video", f"标题{rid}", "作者", "youtube", "https://x/" + rid,
             "2024-01-01", "2024-01-02", "摘要", "[]", "h", "2024-01-02"),
        )
    con.commit()
    con.close()


def test_get_by_ids_returns_mapping(tmp_path):
    db = tmp_path / "atlas.db"
    _seed(db)
    hits = search.get_by_ids(db, ["b", "a", "missing"])
    assert set(hits.keys()) == {"a", "b"}
    assert hits["a"].title == "标题a"
    assert hits["b"].type == "video"


def test_get_by_ids_empty(tmp_path):
    db = tmp_path / "atlas.db"
    _seed(db)
    assert search.get_by_ids(db, []) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_db_search.py -v`
Expected: FAIL — `search.get_by_ids` undefined.

- [ ] **Step 3: Write the implementation**

Append to `src/aishelf/db/search.py` (after the `search` function), reusing the existing `_hit` row mapper:

```python
def get_by_ids(db_path, ids: list[str]) -> dict[str, SearchHit]:
    """Hydrate items by id into a {id: SearchHit} map (missing ids omitted)."""
    if not ids:
        return {}
    con = schema.connect(db_path)
    try:
        schema.init_db(con)
        placeholders = ",".join("?" for _ in ids)
        rows = con.execute(
            f"SELECT * FROM items WHERE id IN ({placeholders})", list(ids)
        ).fetchall()
        return {r["id"]: _hit(r) for r in rows}
    finally:
        con.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_db_search.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/search.py tests/unit/test_db_search.py
git commit -m "feat(db): get_by_ids row hydrator for hybrid retrieval"
```

---

## Task 6: Compute + store embeddings in `sync`

**Files:**
- Modify: `src/aishelf/db/sync.py`
- Test: `tests/unit/test_db_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_db_sync.py` (create if absent, with this import block at the top):

```python
import json

from aishelf import embed
from aishelf.db import schema, vector
from aishelf.db.sync import sync


def _write_video(data_dir, vid, summary="普通摘要"):
    (data_dir / "videos").mkdir(parents=True, exist_ok=True)
    rec = {"id": vid, "type": "video", "title": "标题", "author": "作者甲",
           "platform": "youtube", "source_url": f"https://x/{vid}",
           "published_at": "2024-01-01", "summary": summary, "keywords": [],
           "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}
    (data_dir / "videos" / f"{vid}.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _embedding_row(db_path, vid):
    con = schema.connect(db_path)
    row = con.execute(
        "SELECT embedding, embedding_model, embedding_dim FROM items WHERE id=?", (vid,)
    ).fetchone()
    con.close()
    return row


def test_sync_stores_embeddings_when_configured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])
    sync(data, db)
    row = _embedding_row(db, "v1")
    assert row["embedding"] is not None
    assert row["embedding_model"] == "fake-embed"
    assert row["embedding_dim"] == 3
    assert list(vector.unpack(row["embedding"])) == [1.0, 0.0, 0.0]


def test_sync_skips_embeddings_when_not_configured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    # embed_texts must never be called when unconfigured:
    monkeypatch.setattr(embed, "embed_texts", lambda texts: (_ for _ in ()).throw(AssertionError("called")))
    sync(data, db)
    assert _embedding_row(db, "v1")["embedding"] is None


def test_sync_reembeds_on_model_change(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "model-A")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    sync(data, db)
    assert _embedding_row(db, "v1")["embedding_model"] == "model-A"
    # Same content, new model -> re-embed even though the content hash is unchanged.
    calls = {"n": 0}
    def _embed(texts):
        calls["n"] += 1
        return [[0.0, 1.0] for _ in texts]
    monkeypatch.setattr(embed, "model_name", lambda: "model-B")
    monkeypatch.setattr(embed, "embed_texts", _embed)
    sync(data, db)
    row = _embedding_row(db, "v1")
    assert calls["n"] == 1
    assert row["embedding_model"] == "model-B"
    assert list(vector.unpack(row["embedding"])) == [0.0, 1.0]


def test_sync_embedding_failure_leaves_row_without_crash(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: None)  # service down
    summary = sync(data, db)          # must not raise
    assert summary.added == 1
    assert _embedding_row(db, "v1")["embedding"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_db_sync.py -v`
Expected: FAIL — embeddings not stored (`embedding` is None / model column None).

- [ ] **Step 3: Implement embedding in sync**

Edit `src/aishelf/db/sync.py`. First add imports near the top (after the existing `from aishelf.db ...` lines):

```python
from aishelf import embed
from aishelf.db import vector
```

Add an embed-text helper after `_content_hash`:

```python
def _embed_text(item, note: str) -> str:
    """Text fed to the embedding model — author deliberately excluded so author
    names don't pull unrelated same-author items closer in vector space."""
    return " ".join([item.title, item.summary, " ".join(item.keywords), note]).strip()
```

Now replace the body of `sync` (the `try:` block) with the version below. Changes vs. the original: the `existing` map also carries the embedding model + presence; each item gets a `needs_index` / `needs_emb` decision; embedding-needing items are gathered, batch-embedded once after the loop, and written with a separate `UPDATE`:

```python
    db_path = db_path or default_db_path(data_dir)
    items = load_items(data_dir)
    con = schema.connect(db_path)
    try:
        schema.init_db(con)
        summary = SyncSummary()
        existing = {
            r["id"]: (r["content_hash"], r["embedding_model"], r["has_emb"])
            for r in con.execute(
                "SELECT id, content_hash, embedding_model, "
                "(embedding IS NOT NULL) AS has_emb FROM items"
            )
        }
        synced_at = datetime.now(timezone.utc).isoformat()
        seen: set[str] = set()
        embed_model = embed.model_name()  # None when unconfigured
        to_embed: list[tuple] = []        # (item, note) needing (re)embedding

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
            prev = existing.get(it.id)
            needs_index = prev is None or prev[0] != h
            needs_emb = bool(embed_model) and (
                prev is None or needs_index or prev[1] != embed_model or not prev[2]
            )
            if not needs_index and not needs_emb:
                summary.unchanged += 1
                continue
            if needs_index:
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
                if prev is not None:
                    summary.updated += 1
                else:
                    summary.added += 1
            if needs_emb:
                to_embed.append((it, note))

        if to_embed and embed_model:
            vectors = embed.embed_texts([_embed_text(it, note) for it, note in to_embed])
            if vectors:
                for (it, _note), vec in zip(to_embed, vectors):
                    con.execute(
                        "UPDATE items SET embedding=?, embedding_model=?, embedding_dim=? "
                        "WHERE id=?",
                        (vector.pack(vec), embed_model, len(vec), it.id),
                    )

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_db_sync.py -v`
Expected: PASS (4 new tests + any pre-existing sync tests).

- [ ] **Step 5: Run the existing sync/db suite for regressions**

Run: `pytest tests/unit/test_db_sync.py tests/unit/test_db_search.py -v`
Expected: PASS (no regressions — embedding is opt-in; unconfigured runs behave as before).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/db/sync.py tests/unit/test_db_sync.py
git commit -m "feat(db): sync computes + stores embeddings incrementally (re-embed on change/model switch)"
```

---

## Task 7: Hybrid `retrieve()` in `ask.py`

**Files:**
- Modify: `src/aishelf/site/ask.py`
- Test: `tests/unit/test_site_ask.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_site_ask.py` (top-of-file imports `json`, `ask`, `Source` already exist; add `from aishelf import embed` and `from aishelf.db.sync import sync`):

```python
from aishelf import embed as _embed
from aishelf.db.sync import sync as _sync


def _build_db(tmp_path, monkeypatch, items, embed_map):
    """Write videos + a fake-embedded atlas.db. embed_map: text-substring -> vec."""
    data = tmp_path / "data"
    (data / "videos").mkdir(parents=True)
    for it in items:
        (data / "videos" / f"{it['id']}.json").write_text(
            json.dumps(it, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(_embed, "model_name", lambda: "fake-embed")

    def _texts(texts):
        out = []
        for t in texts:
            vec = next((v for sub, v in embed_map.items() if sub in t), [0.0, 0.0, 1.0])
            out.append(vec)
        return out

    monkeypatch.setattr(_embed, "embed_texts", _texts)
    db = tmp_path / "atlas.db"
    _sync(data, db)
    return db


def _vid(vid, title, summary):
    return {"id": vid, "type": "video", "title": title, "author": "作者",
            "platform": "youtube", "source_url": f"https://x/{vid}",
            "published_at": "2024-01-01", "summary": summary, "keywords": [],
            "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}


def test_retrieve_hybrid_recalls_semantic_match(tmp_path, monkeypatch):
    # FTS would not match an English title from a Chinese query, but the vector does.
    db = _build_db(tmp_path, monkeypatch,
                   [_vid("v1", "Scaling laws explained", "training compute"),
                    _vid("v2", "园艺入门", "如何种花")],
                   {"Scaling": [1.0, 0.0, 0.0], "园艺": [0.0, 1.0, 0.0]})
    monkeypatch.setattr(ask.embed, "embed_query", lambda q: [1.0, 0.0, 0.0])
    sources = ask.retrieve(db, "扩展定律", k=6)
    assert [s.id for s in sources] == ["v1"]   # semantic hit; gardening pruned by floor


def test_retrieve_hybrid_keeps_fts_safety_net(tmp_path, monkeypatch):
    # v2 is a weak vector match (below floor) but an exact FTS hit -> kept.
    db = _build_db(tmp_path, monkeypatch,
                   [_vid("v1", "Scaling laws", "compute"),
                    _vid("v2", "向量数据库实战", "讲解向量数据库")],
                   {"Scaling": [1.0, 0.0, 0.0], "向量": [0.0, 0.0, 1.0]})
    monkeypatch.setattr(ask.embed, "embed_query", lambda q: [1.0, 0.0, 0.0])
    ids = [s.id for s in ask.retrieve(db, "向量数据库", k=6)]
    assert "v2" in ids    # exact FTS hit survives despite low cosine


def test_retrieve_falls_back_to_fts_when_embedding_unavailable(tmp_path, monkeypatch):
    db = _build_db(tmp_path, monkeypatch,
                   [_vid("v1", "向量数据库实战", "讲解向量数据库")],
                   {"向量": [1.0, 0.0, 0.0]})
    monkeypatch.setattr(ask.embed, "embed_query", lambda q: None)  # service down
    sources = ask.retrieve(db, "向量数据库", k=6)
    assert [s.id for s in sources] == ["v1"]  # pure-FTS path, today's behavior
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_site_ask.py -k retrieve_hybrid -v`
Expected: FAIL — `ask.embed` attribute / hybrid behavior absent.

- [ ] **Step 3: Implement the hybrid path**

Edit `src/aishelf/site/ask.py`:

(a) Add imports near the existing imports:

```python
from aishelf import embed
from aishelf.db import search as db_search
from aishelf.db import vector
```

(`db_search` is already imported — keep one import; add `embed` and `vector`.)

(b) Add constants beside the existing ones:

```python
SIMILARITY_FLOOR = 0.30
CANDIDATE_N = 20
```

(c) Replace the current `retrieve` with a dispatcher + two paths. The FTS-only path is exactly today's logic (extracted), so the no-embedding case is a behavioral no-op:

```python
def retrieve(db_path, question: str, *, k: int = DEFAULT_K) -> list[Source]:
    """Top-k relevant sources for the question.

    Hybrid when an embedding service is configured/reachable: vector recall over
    the whole corpus (semantic / cross-lingual) unioned with FTS5 (exact-term
    safety net), re-ranked by cosine and floored. Falls back to pure FTS5 + the
    bigram-overlap floor when embeddings are unavailable — identical to before.
    """
    qv = embed.embed_query(question)
    if qv is None:
        return _retrieve_fts_only(db_path, question, k)
    return _retrieve_hybrid(db_path, question, qv, k)


def _retrieve_fts_only(db_path, question: str, k: int) -> list[Source]:
    hits = db_search.search(db_path, question, limit=k, mode="or")
    sources = [_source_from_hit(h) for h in hits]
    return relevant_sources(question, sources)


def _retrieve_hybrid(db_path, question: str, qv: list[float], k: int) -> list[Source]:
    ids, matrix = vector.load_embeddings(db_path, len(qv))
    ranked = vector.cosine_search(qv, ids, matrix, top_n=CANDIDATE_N)
    fts_hits = db_search.search(db_path, question, limit=CANDIDATE_N, mode="or")

    kept: list[str] = []
    seen: set[str] = set()
    for cid, score in ranked:                  # vector hits above the floor, cosine order
        if score >= SIMILARITY_FLOOR and cid not in seen:
            kept.append(cid)
            seen.add(cid)
    for h in fts_hits:                          # FTS exact hits append (bm25 order) — safety net
        if h.id not in seen:
            kept.append(h.id)
            seen.add(h.id)
    kept = kept[:k]
    return _sources_for_ids(db_path, kept)
```

(d) Add the hit→Source and id→Source hydrators (factor the existing `Source(...)` construction out of the old `retrieve`):

```python
def _source_from_hit(h) -> Source:
    return Source(
        id=h.id, type=h.type, title=h.title, author=h.author,
        platform=h.platform, summary=h.summary, keywords=h.keywords,
        note=_note_for(h.id),
    )


def _sources_for_ids(db_path, ids: list[str]) -> list[Source]:
    rows = db_search.get_by_ids(db_path, ids)
    return [_source_from_hit(rows[i]) for i in ids if i in rows]
```

- [ ] **Step 4: Run the new tests**

Run: `pytest tests/unit/test_site_ask.py -k retrieve -v`
Expected: PASS — including the pre-existing `test_retrieve_finds_note_only_match` and `test_retrieve_prunes_irrelevant_tail` (these run with `ATLAS_EMBED_*` unset, so `embed_query` returns `None` → the FTS-only path → unchanged behavior).

- [ ] **Step 5: Run the full ask + route suite**

Run: `pytest tests/unit/test_site_ask.py tests/unit/test_site_ask_routes.py -v`
Expected: PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/site/ask.py tests/unit/test_site_ask.py
git commit -m "feat(ask): hybrid retrieve (vector + FTS5) with graceful FTS-only fallback"
```

---

## Task 8: Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Document config in CLAUDE.md**

In `CLAUDE.md`, under `## Config`, add after the `ATLAS_CHAT_*` bullet:

```markdown
- `ATLAS_EMBED_BASE_URL` / `ATLAS_EMBED_API_KEY` / `ATLAS_EMBED_MODEL` — a
  self-hosted, OpenAI-compatible embedding service powering `/ask` semantic
  retrieval. **No default** (the chat provider does not serve embeddings); unset
  ⇒ semantic retrieval is silently disabled and `/ask` uses pure FTS5. After
  configuring, run `python -m aishelf.db sync --rebuild` once to backfill
  embeddings; changing the model triggers re-embedding on the next sync.
```

Also update the `aishelf.site` module description for `ask.py` to mention the hybrid path, and add `embed.py` / `aishelf/db/vector.py` to the architecture bullets.

- [ ] **Step 2: Document the flow in ARCHITECTURE.md**

In `docs/ARCHITECTURE.md`:
- Add `aishelf/embed.py` and `aishelf/db/vector.py` to the component tables.
- Update the **Ask** flow bullet (section 4) to describe hybrid retrieval: query embedded once, vector recall over the corpus unioned with FTS5 exact hits, cosine rerank + floor, graceful fallback to pure FTS5 when `ATLAS_EMBED_*` is unset/unreachable.
- Add an `ATLAS_EMBED_*` note to the config/running section and the `numpy` dependency to the tech-stack list.
- Update the test count in the status header to the number `pytest` reports after this work (run `pytest -q | tail -1`).

- [ ] **Step 3: Verify the full suite**

Run: `pytest -q`
Expected: all pass. Capture the count for the ARCHITECTURE header.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/ARCHITECTURE.md
git commit -m "docs: document ATLAS_EMBED_* and /ask hybrid retrieval"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- `embed.py` client (no default, None on error) → Task 2 ✓
- BLOB columns → Task 3 ✓
- numpy cosine, no vector DB → Tasks 1, 4 ✓
- Embed at sync, incremental, re-embed on model change → Task 6 ✓
- Hybrid vector-primary + FTS5 safety net + cosine floor → Task 7 ✓
- Graceful fallback to pure FTS5 → Task 7 (dispatcher + test) ✓
- Author excluded from embedded text → Task 6 (`_embed_text`) ✓
- Config + `sync --rebuild` backfill docs → Task 8 ✓
- Out-of-scope items (no `/search` changes, no ANN) → respected (Tasks touch only `/ask` retrieval) ✓

**Placeholder scan:** none — every code/test step has complete content.

**Type consistency:** `embed.embed_query`/`embed_texts`/`model_name` (Task 2) used identically in Tasks 6–7; `vector.pack`/`unpack`/`load_embeddings(db, dim, *, type)`/`cosine_search(qv, ids, matrix, *, top_n)` (Task 4) match their call sites in Tasks 6–7; `search.get_by_ids` (Task 5) returns `{id: SearchHit}` consumed by `_sources_for_ids` (Task 7); `SearchHit` fields (`.id/.type/.title/.author/.platform/.summary/.keywords`) match `_source_from_hit`.

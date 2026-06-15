# Knowledge Graph 3D Globe + Aliases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 2D Cytoscape `/graph` with a Three.js wireframe-sphere ("tech globe") where nodes sit on the sphere surface (placed by PCA of their embeddings), edges are glowing arcs, the globe rotates/zooms, and node labels are short DeepSeek-generated aliases.

**Architecture:** A new `items.alias` column holds ≤8-char aliases generated at sync (on title change). `db/graph.py`'s `load_graph` enriches each node with its alias and a read-time PCA-of-embeddings unit-sphere position `(x,y,z)`. `/api/graph` is unchanged in code (returns the richer nodes). `graph.html` is rewritten with Three.js.

**Tech Stack:** Python 3.11+, SQLite, numpy (PCA), OpenAI SDK (DeepSeek via `ATLAS_CHAT_*`), FastAPI/Jinja2, Three.js r128 + OrbitControls + CSS2DRenderer (CDN), pytest.

**Spec:** `docs/superpowers/specs/2026-06-15-knowledge-graph-3d-globe-design.md`

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/aishelf/db/schema.py` | Modify | Add `alias TEXT` to `items`. |
| `src/aishelf/alias.py` | Create | LLM alias client (`ATLAS_CHAT_*`, batched JSON, None on fail). |
| `src/aishelf/db/sync.py` | Modify | Generate + store aliases for new/title-changed items. |
| `src/aishelf/db/graph.py` | Modify | `load_graph` adds `alias` + PCA sphere `(x,y,z)`; `_hash_point`, `_sphere_positions`. |
| `src/aishelf/site/templates/graph.html` | Modify (rewrite) | Three.js wireframe globe. |
| `CLAUDE.md`, `docs/ARCHITECTURE.md` | Modify | Document aliases + 3D globe. |
| `tests/unit/test_alias.py` | Create | Alias client tests. |
| `tests/unit/test_db_sync.py` | Modify | Alias-at-sync tests. |
| `tests/unit/test_db_graph.py` | Modify | `load_graph` alias + position tests. |
| `tests/unit/test_site_graph_routes.py` | Modify | Update page-render test for Three.js. |

---

## Task 1: `items.alias` column

**Files:** Modify `src/aishelf/db/schema.py`; Test `tests/unit/test_db_graph.py` (append).

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_db_graph.py`:

```python
def test_items_table_has_alias_column(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
    con.close()
    assert "alias" in cols
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_db_graph.py::test_items_table_has_alias_column -v`
Expected: FAIL — no `alias` column.

- [ ] **Step 3: Add the column** — in `src/aishelf/db/schema.py`, add `alias TEXT` to the `items` table in `SCHEMA_SQL`, immediately after the `embedding_dim INTEGER,` line:

```sql
  embedding_dim     INTEGER,
  alias             TEXT,
  content_hash  TEXT NOT NULL,
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_db_graph.py::test_items_table_has_alias_column -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/schema.py tests/unit/test_db_graph.py
git commit -m "feat(db): add alias column to items for graph node labels"
```
End every commit message in this plan with this trailer (after a blank line):
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## Task 2: Alias client (`aishelf/alias.py`)

**Files:** Create `src/aishelf/alias.py`; Test `tests/unit/test_alias.py`.

- [ ] **Step 1: Write the failing tests** — create `tests/unit/test_alias.py`:

```python
from types import SimpleNamespace

from aishelf import alias


class _Completions:
    def __init__(self, content):
        self.content = content
        self.captured = {}

    def create(self, **kwargs):
        self.captured = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


class _FakeClient:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=_Completions(content))


def _configure(monkeypatch):
    monkeypatch.setenv("ATLAS_CHAT_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("ATLAS_CHAT_API_KEY", "k")
    monkeypatch.setenv("ATLAS_CHAT_MODEL", "fake-chat")


def test_not_configured_returns_none(monkeypatch):
    monkeypatch.delenv("ATLAS_CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("ATLAS_CHAT_MODEL", raising=False)
    assert alias.is_configured() is False
    assert alias.generate_aliases([("t", "s")]) is None


def test_generate_aliases_parses_json_array(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('["RAG综述", "Agent构建"]'))
    assert alias.generate_aliases([("RAG paper", "x"), ("Agent guide", "y")]) == ["RAG综述", "Agent构建"]


def test_generate_aliases_strips_code_fence(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('```json\n["甲", "乙"]\n```'))
    assert alias.generate_aliases([("a", ""), ("b", "")]) == ["甲", "乙"]


def test_generate_aliases_caps_length(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('["一二三四五六七八九十甲乙"]'))
    out = alias.generate_aliases([("a", "")])
    assert len(out) == 1 and len(out[0]) <= 10


def test_empty_input_returns_none(monkeypatch):
    _configure(monkeypatch)
    assert alias.generate_aliases([]) is None


def test_wrong_length_returns_none(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('["仅一个"]'))
    assert alias.generate_aliases([("a", ""), ("b", "")]) is None  # 1 alias for 2 inputs


def test_client_error_returns_none(monkeypatch):
    _configure(monkeypatch)

    def _boom(s):
        raise RuntimeError("down")

    monkeypatch.setattr(alias, "get_client", _boom)
    assert alias.generate_aliases([("a", "")]) is None
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_alias.py -v`
Expected: FAIL — `aishelf.alias` does not exist.

- [ ] **Step 3: Create `src/aishelf/alias.py`:**

```python
"""Short-alias client for graph node labels (LLM, OpenAI-compatible chat).

Reads ATLAS_CHAT_* (the same chat model that answers /ask, e.g. DeepSeek).
Unset ⇒ disabled (returns None). Any error or parse failure also returns None,
so callers fall back to a truncated title. Lives at the package root so the db
layer can use it without importing aishelf.site (mirrors embed.py).
"""

from __future__ import annotations

import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

ALIAS_BATCH_SIZE = 20
ALIAS_MAX_CHARS = 10  # safety cap; the prompt asks for <= 8

_PROMPT = (
    "为下列每条内容各起一个不超过8个汉字的简短中文别名，用于知识图谱的节点标签，"
    "要能概括主题、尽量短。只返回一个 JSON 字符串数组，元素顺序与输入编号一致，"
    "不要输出任何额外文字或解释。\n\n"
)


def get_alias_settings() -> dict[str, str] | None:
    base = os.environ.get("ATLAS_CHAT_BASE_URL")
    model = os.environ.get("ATLAS_CHAT_MODEL")
    if not base or not model:
        return None
    return {"base_url": base, "api_key": os.environ.get("ATLAS_CHAT_API_KEY", ""), "model": model}


def is_configured() -> bool:
    return get_alias_settings() is not None


def get_client(settings: dict[str, str]) -> OpenAI:
    return OpenAI(base_url=settings["base_url"], api_key=settings["api_key"] or "none", timeout=60.0)


def _extract_json_array(text: str) -> str:
    i = text.find("[")
    j = text.rfind("]")
    if i == -1 or j == -1 or j < i:
        raise ValueError("no JSON array in response")
    return text[i:j + 1]


def _clean(a: str) -> str:
    return (a or "").strip().strip('"「」“”').strip()[:ALIAS_MAX_CHARS]


def generate_aliases(pairs: list[tuple[str, str]]) -> list[str] | None:
    """≤8-char aliases for (title, summary) pairs, or None if unconfigured /
    empty / on any error or parse mismatch. Batched (ALIAS_BATCH_SIZE per call);
    each batch must return a JSON array of the same length (all-or-nothing)."""
    s = get_alias_settings()
    if s is None or not pairs:
        return None
    try:
        client = get_client(s)
        out: list[str] = []
        for i in range(0, len(pairs), ALIAS_BATCH_SIZE):
            chunk = pairs[i:i + ALIAS_BATCH_SIZE]
            listing = "\n".join(
                f"{n + 1}. {title} ｜ {(summary or '')[:80]}"
                for n, (title, summary) in enumerate(chunk)
            )
            resp = client.chat.completions.create(
                model=s["model"],
                messages=[{"role": "user", "content": _PROMPT + listing}],
                stream=False,
            )
            content = resp.choices[0].message.content or ""
            arr = json.loads(_extract_json_array(content))
            if not isinstance(arr, list) or len(arr) != len(chunk):
                return None
            out.extend(_clean(str(x)) for x in arr)
        return out
    except Exception as exc:  # degrade to truncated-title fallback, never crash sync
        logger.warning("alias generation failed: %s", exc)
        return None
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_alias.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/alias.py tests/unit/test_alias.py
git commit -m "feat(alias): LLM short-alias client (ATLAS_CHAT_*, batched, None on fail)"
```

---

## Task 3: Generate + store aliases in `sync`

**Files:** Modify `src/aishelf/db/sync.py`; Test `tests/unit/test_db_sync.py` (append).

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_db_sync.py` (the file already imports `json`, `from aishelf import embed`, `from aishelf.db import schema, vector, graph as _graph`, `from aishelf.db.sync import sync`, and defines `_write_video`/`_embedding_row`; add `from aishelf import alias as _alias`):

```python
from aishelf import alias as _alias


def _alias_of(db_path, vid):
    con = schema.connect(db_path)
    row = con.execute("SELECT alias FROM items WHERE id=?", (vid,)).fetchone()
    con.close()
    return row["alias"]


def test_sync_stores_alias_for_new_item(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)              # isolate alias
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: ["别名一"] * len(pairs))
    sync(data, db)
    assert _alias_of(db, "v1") == "别名一"


def test_sync_skips_alias_when_unconfigured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)  # unconfigured/failed
    sync(data, db)
    assert _alias_of(db, "v1") is None


def test_sync_regenerates_alias_on_title_change_not_note(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    calls = {"n": 0}

    def _gen(pairs):
        calls["n"] += 1
        return [f"别名{calls['n']}"] * len(pairs)

    monkeypatch.setattr(_alias, "generate_aliases", _gen)
    sync(data, db)
    assert calls["n"] == 1 and _alias_of(db, "v1") == "别名1"

    # note-only change: alias must NOT regenerate
    (data / "notes").mkdir(exist_ok=True)
    (data / "notes" / "v1.json").write_text(
        json.dumps({"id": "v1", "text": "新笔记", "updated_at": "2024-02-01"}, ensure_ascii=False),
        encoding="utf-8")
    sync(data, db)
    assert calls["n"] == 1 and _alias_of(db, "v1") == "别名1"

    # title change: alias regenerates
    rec = json.loads((data / "videos" / "v1.json").read_text(encoding="utf-8"))
    rec["title"] = "全新的标题"
    (data / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    sync(data, db)
    assert calls["n"] == 2 and _alias_of(db, "v1") == "别名2"
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_db_sync.py -k alias -v`
Expected: FAIL — sync doesn't touch `alias`.

- [ ] **Step 3: Implement in `src/aishelf/db/sync.py`**

(a) Add `alias` to the package import. The line is `from aishelf import embed`. Change to:

```python
from aishelf import embed, alias
```

(b) Extend the `existing` map query + tuple to carry `title` and alias-presence. Replace:

```python
        existing = {
            r["id"]: (r["content_hash"], r["embedding_model"], r["has_emb"])
            for r in con.execute(
                "SELECT id, content_hash, embedding_model, "
                "(embedding IS NOT NULL) AS has_emb FROM items"
            )
        }
```

with:

```python
        existing = {
            r["id"]: (r["content_hash"], r["embedding_model"], r["has_emb"],
                      r["title"], r["has_alias"])
            for r in con.execute(
                "SELECT id, content_hash, embedding_model, "
                "(embedding IS NOT NULL) AS has_emb, title, "
                "(alias IS NOT NULL AND alias != '') AS has_alias FROM items"
            )
        }
```

(c) Add a `to_alias` accumulator next to `to_embed`. The line is `to_embed: list[tuple] = []        # (item, note) needing (re)embedding`. After it add:

```python
        to_alias: list = []               # items needing a (re)generated alias
```

(d) In the per-item loop, compute `needs_alias`, include it in the skip guard, and collect. Replace this block:

```python
            needs_emb = bool(embed_model) and (
                prev is None or needs_index or prev[1] != embed_model or not prev[2]
            )
            if not needs_index and not needs_emb:
                summary.unchanged += 1
                continue
```

with:

```python
            needs_emb = bool(embed_model) and (
                prev is None or needs_index or prev[1] != embed_model or not prev[2]
            )
            needs_alias = prev is None or it.title != prev[3] or not prev[4]
            if not needs_index and not needs_emb and not needs_alias:
                summary.unchanged += 1
                continue
```

and at the end of the loop body, after `if needs_emb: to_embed.append((it, note))`, add:

```python
            if needs_alias:
                to_alias.append(it)
```

(e) After the embedding-write block and before the stale-prune block (i.e. right after the `elif vectors:` warning for embeddings), add the alias-write block:

```python
        if to_alias:
            new_aliases = alias.generate_aliases([(it.title, it.summary) for it in to_alias])
            if new_aliases and len(new_aliases) == len(to_alias):
                for it, a in zip(to_alias, new_aliases):
                    con.execute("UPDATE items SET alias=? WHERE id=?", (a, it.id))
            elif new_aliases:
                logger.warning(
                    "generate_aliases returned %d for %d items; skipping alias update",
                    len(new_aliases), len(to_alias),
                )
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_db_sync.py -v`
Expected: PASS (alias tests + all pre-existing sync tests).

- [ ] **Step 5: Full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/db/sync.py tests/unit/test_db_sync.py
git commit -m "feat(db): sync generates + stores node aliases (on title change)"
```

---

## Task 4: `load_graph` adds alias + sphere positions

**Files:** Modify `src/aishelf/db/graph.py`; Test `tests/unit/test_db_graph.py` (append).

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_db_graph.py` (helpers `_seed_item`/`_edge_set` already exist; `_seed_item(con, rid, typ, vec)` inserts an item with an embedding):

```python
import math


def test_hash_point_on_unit_sphere_and_deterministic():
    p1 = graph._hash_point("abc")
    p2 = graph._hash_point("abc")
    assert p1 == p2
    assert math.isclose(math.sqrt(sum(c * c for c in p1)), 1.0, abs_tol=1e-5)


def test_load_graph_nodes_have_alias_and_unit_position(tmp_path):
    db = tmp_path / "atlas.db"
    con = schema.connect(db)
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0, 0.1])
    _seed_item(con, "b", "blog", [0.9, 0.2, 0.0])
    _seed_item(con, "c", "video", [0.0, 1.0, 0.2])
    con.execute("UPDATE items SET alias='甲' WHERE id='a'")
    con.commit(); con.close()
    g = graph.load_graph(db)
    a = next(n for n in g["nodes"] if n["id"] == "a")
    assert a["alias"] == "甲"
    assert {"x", "y", "z"} <= set(a.keys())
    norm = math.sqrt(a["x"] ** 2 + a["y"] ** 2 + a["z"] ** 2)
    assert math.isclose(norm, 1.0, abs_tol=1e-5)
    # node without an alias falls back to "" (frontend truncates the title)
    b = next(n for n in g["nodes"] if n["id"] == "b")
    assert b["alias"] == ""


def test_load_graph_hash_position_when_no_embedding(tmp_path):
    db = tmp_path / "atlas.db"
    con = schema.connect(db)
    schema.init_db(con)
    # item with no embedding -> hash placement, still unit-norm, still present
    con.execute(
        "INSERT INTO items (id, type, title, author, platform, source_url, "
        "published_at, collected_at, summary, keywords, content_hash, synced_at) "
        "VALUES ('x','blog','标题x','作者','p','https://x/x','2024-01-01',"
        "'2024-01-02','s','[]','h','2024-01-02')")
    con.commit(); con.close()
    g = graph.load_graph(db)
    x = next(n for n in g["nodes"] if n["id"] == "x")
    norm = math.sqrt(x["x"] ** 2 + x["y"] ** 2 + x["z"] ** 2)
    assert math.isclose(norm, 1.0, abs_tol=1e-5)
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_db_graph.py -k "hash_point or unit_position or hash_position" -v`
Expected: FAIL — `_hash_point` undefined / nodes lack `alias`/`x`.

- [ ] **Step 3: Implement in `src/aishelf/db/graph.py`**

(a) Add `import hashlib` at the top (after `import numpy as np`):

```python
import hashlib

import numpy as np
```

(b) Add the placement helpers (place them after `_canon`):

```python
def _hash_point(item_id: str) -> tuple[float, float, float]:
    """Deterministic point uniformly on the unit sphere from an id (fallback
    placement for nodes without a usable embedding)."""
    h = hashlib.sha1(item_id.encode("utf-8")).digest()
    u = int.from_bytes(h[0:4], "big") / 2 ** 32
    v = int.from_bytes(h[4:8], "big") / 2 ** 32
    z = 2.0 * u - 1.0
    theta = 2.0 * np.pi * v
    r = (1.0 - z * z) ** 0.5
    return (float(r * np.cos(theta)), float(r * np.sin(theta)), float(z))


def _sphere_positions(node_ids: list[str], groups: dict) -> dict[str, tuple[float, float, float]]:
    """Unit-sphere position per node: PCA the largest embedding group to 3D and
    L2-normalize each row; ids without an embedding (or when <3 are embedded, or
    PCA is degenerate) get a deterministic hash point. Every node gets a position."""
    pos: dict[str, tuple[float, float, float]] = {}
    if groups:
        dim = max(groups, key=lambda d: len(groups[d][0]))
        ids, mat = groups[dim]
        if len(ids) >= 3:
            centered = mat - mat.mean(axis=0)
            try:
                _u, _s, vt = np.linalg.svd(centered, full_matrices=False)
                coords = centered @ vt[:3].T
                if coords.shape[1] < 3:
                    coords = np.pad(coords, ((0, 0), (0, 3 - coords.shape[1])))
                norms = np.linalg.norm(coords, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                unit = coords / norms
                for sid, row in zip(ids, unit):
                    pos[sid] = (float(row[0]), float(row[1]), float(row[2]))
            except np.linalg.LinAlgError:
                pass
    for sid in node_ids:
        if sid not in pos:
            pos[sid] = _hash_point(sid)
    return pos
```

(c) Update `load_graph` to read `alias`, load embeddings, compute positions, and emit the new node fields. Replace the `try` block's queries and the final `nodes = [...]` construction.

Change the query line:
```python
        node_rows = con.execute("SELECT id, type, title, author FROM items").fetchall()
        edge_rows = con.execute("SELECT src, dst, weight FROM edges").fetchall()
```
to:
```python
        node_rows = con.execute("SELECT id, type, title, alias FROM items").fetchall()
        edge_rows = con.execute("SELECT src, dst, weight FROM edges").fetchall()
        groups = _load_groups(con)
```

Change the final node assembly:
```python
    nodes = [
        {"id": r["id"], "type": r["type"], "title": r["title"],
         "author": r["author"], "degree": degree.get(r["id"], 0)}
        for r in node_rows
    ]
    return {"nodes": nodes, "edges": edges}
```
to:
```python
    positions = _sphere_positions([r["id"] for r in node_rows], groups)
    nodes = []
    for r in node_rows:
        x, y, z = positions[r["id"]]
        nodes.append({
            "id": r["id"], "type": r["type"], "title": r["title"],
            "alias": r["alias"] or "", "degree": degree.get(r["id"], 0),
            "x": x, "y": y, "z": z,
        })
    return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_db_graph.py -v`
Expected: PASS (all graph tests).

- [ ] **Step 5: Run sync + route tests for regressions**

Run: `pytest tests/unit/test_db_sync.py tests/unit/test_site_graph_routes.py -v`
Expected: PASS (existing `test_api_graph_shape` still passes — it asserts a subset of node fields and `edges == []`).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/db/graph.py tests/unit/test_db_graph.py
git commit -m "feat(db): load_graph adds alias + PCA unit-sphere positions"
```

---

## Task 5: Three.js wireframe-globe page

**Files:** Modify (rewrite) `src/aishelf/site/templates/graph.html`; Modify `tests/unit/test_site_graph_routes.py`.

- [ ] **Step 1: Update the page-render test** — in `tests/unit/test_site_graph_routes.py`, replace `test_graph_page_renders` with one that asserts the Three.js markers (the old asserts referenced Cytoscape and `id="cy"`):

```python
def test_graph_page_renders(client):
    r = client.get("/graph")
    assert r.status_code == 200
    assert "/api/graph" in r.text
    assert "three@0.128" in r.text          # Three.js CDN pin
    assert 'id="globe"' in r.text           # the WebGL container
    assert "OrbitControls" in r.text        # rotate/zoom controls
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_site_graph_routes.py::test_graph_page_renders -v`
Expected: FAIL — current page has Cytoscape, not Three.js.

- [ ] **Step 3: Rewrite `src/aishelf/site/templates/graph.html`** with exactly:

```html
{% extends "base.html" %}
{% block title %}图谱 · Atlas{% endblock %}
{% block content %}
<div class="globe-wrap">
  <div class="globe-bar">
    <span class="globe-title">知识星球</span>
    <span class="globe-hint">语义相近的内容聚在一起 · 拖拽旋转 · 滚轮缩放 · 点击进入详情</span>
    <span class="globe-spacer"></span>
    <input id="globeSearch" class="globe-search" placeholder="高亮节点…" />
    <div class="globe-filters" id="globeFilters">
      <button type="button" data-f="all" class="on">全部</button>
      <button type="button" data-f="video">视频</button>
      <button type="button" data-f="blog">博客</button>
    </div>
  </div>
  <div id="globe" class="globe-canvas"></div>
  <div id="globeTip" class="globe-tip" hidden></div>
  <div id="globeEmpty" class="globe-empty" hidden>
    图谱暂时没有数据。先在 <a href="/collect">Hermes</a> 采集内容，配置好 embedding 服务后运行一次
    <code>python -m aishelf.db sync --rebuild</code>。
  </div>
</div>
<style>
  main:has(.globe-wrap) { max-width: none; padding: 0; }
  .globe-wrap { position: relative; display: flex; flex-direction: column; height: calc(100vh - 57px); height: calc(100dvh - 57px); background: #05070f; }
  .globe-bar { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid #16203a; background: #0a0f1e; color: #cdd8ef; flex: none; z-index: 2; }
  .globe-title { font-weight: 700; color: #eaf2ff; }
  .globe-hint { font-size: 12px; color: #5f6f93; }
  .globe-spacer { margin-left: auto; }
  .globe-search { height: 32px; border: 1px solid #1d2a48; border-radius: 8px; padding: 0 10px; font-size: 13px; outline: none; background: #0c1426; color: #dce6fb; }
  .globe-search:focus { border-color: #2f6fe0; }
  .globe-filters button { height: 30px; padding: 0 12px; margin-left: 6px; border: 1px solid #1d2a48; background: #0c1426; color: #93a3c8; border-radius: 999px; cursor: pointer; font-size: 13px; }
  .globe-filters button.on { background: #2f6fe0; border-color: #2f6fe0; color: #fff; }
  .globe-canvas { flex: 1; min-height: 0; position: relative; background: radial-gradient(1200px 800px at 50% 30%, #0c1730, #05070f 70%); cursor: grab; }
  .node-label { color: #bcd4ff; font-size: 11px; font-family: -apple-system, "PingFang SC", sans-serif; text-shadow: 0 0 6px rgba(20,80,180,.9); pointer-events: none; white-space: nowrap; }
  .globe-tip { position: absolute; z-index: 3; max-width: 320px; background: rgba(8,14,28,.94); color: #e7eefb; border: 1px solid #24365f; border-radius: 8px; padding: 6px 10px; font-size: 12px; line-height: 1.5; pointer-events: none; }
  .globe-empty { position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); max-width: 460px; text-align: center; color: #8aa0cc; font-size: 14px; line-height: 1.7; }
  .globe-empty code { background: #111c33; padding: 2px 6px; border-radius: 6px; }
</style>
<script src="https://unpkg.com/three@0.128.0/build/three.min.js"></script>
<script src="https://unpkg.com/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script src="https://unpkg.com/three@0.128.0/examples/js/renderers/CSS2DRenderer.js"></script>
<script>
(async function () {
  let data;
  try { data = await (await fetch('/api/graph')).json(); }
  catch (e) { data = { nodes: [], edges: [] }; }
  if (!data.nodes || !data.nodes.length) { document.getElementById('globeEmpty').hidden = false; return; }

  const container = document.getElementById('globe');
  const tip = document.getElementById('globeTip');
  const W = () => container.clientWidth, H = () => container.clientHeight;
  const R = 100;
  const COLOR = { video: 0xff9a3c, blog: 0x4cc2ff };

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, W() / H(), 1, 5000);
  camera.position.set(0, 0, R * 3.2);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  renderer.setSize(W(), H());
  container.appendChild(renderer.domElement);

  const labelRenderer = new THREE.CSS2DRenderer();
  labelRenderer.setSize(W(), H());
  labelRenderer.domElement.style.position = 'absolute';
  labelRenderer.domElement.style.top = '0';
  labelRenderer.domElement.style.left = '0';
  labelRenderer.domElement.style.pointerEvents = 'none';
  container.appendChild(labelRenderer.domElement);

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.6;
  controls.enablePan = false;
  controls.minDistance = R * 1.3;
  controls.maxDistance = R * 8;

  scene.add(new THREE.AmbientLight(0x88aaff, 0.9));
  const pl = new THREE.PointLight(0x66ccff, 1.1); pl.position.set(R * 2, R * 2, R * 3); scene.add(pl);

  // wireframe sphere + faint inner fill
  scene.add(new THREE.Mesh(
    new THREE.SphereGeometry(R, 36, 24),
    new THREE.MeshBasicMaterial({ color: 0x16e0ff, wireframe: true, transparent: true, opacity: 0.13 })));
  scene.add(new THREE.Mesh(
    new THREE.SphereGeometry(R * 0.985, 36, 24),
    new THREE.MeshBasicMaterial({ color: 0x0a1c38, transparent: true, opacity: 0.45 })));

  // nodes
  const nodeMeshes = [], byId = {};
  const nodeGeo = new THREE.SphereGeometry(1, 16, 16);
  for (const n of data.nodes) {
    n.href = (n.type === 'video' ? '/videos/' : '/blogs/') + encodeURIComponent(n.id);
    const size = 2.2 + 0.7 * Math.min(n.degree || 0, 8);
    const mesh = new THREE.Mesh(nodeGeo, new THREE.MeshBasicMaterial({ color: COLOR[n.type] || 0x9aa6bb, transparent: true, opacity: 1 }));
    mesh.scale.setScalar(size);
    mesh.position.set(n.x * R, n.y * R, n.z * R);
    mesh.userData = n;
    scene.add(mesh); nodeMeshes.push(mesh); byId[n.id] = mesh;

    const div = document.createElement('div');
    div.className = 'node-label';
    div.textContent = n.alias || (n.title.length > 10 ? n.title.slice(0, 10) + '…' : n.title);
    const label = new THREE.CSS2DObject(div);
    label.position.set(0, size + 2, 0);
    mesh.add(label);
    n._label = label;
  }

  // edges as outward-bulging arcs
  const edgeLines = [];
  for (const e of data.edges) {
    const a = byId[e.source], b = byId[e.target];
    if (!a || !b) continue;
    const mid = a.position.clone().add(b.position).normalize().multiplyScalar(R * 1.28);
    const curve = new THREE.QuadraticBezierCurve3(a.position.clone(), mid, b.position.clone());
    const geo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(24));
    const mat = new THREE.LineBasicMaterial({ color: 0x39b9ff, transparent: true, opacity: 0.16 + 0.5 * Math.max(0, (e.weight || 0.5) - 0.4) });
    const line = new THREE.Line(geo, mat);
    line.userData = { source: e.source, target: e.target };
    scene.add(line); edgeLines.push(line);
  }

  // hover (tooltip + pause spin) / click (open detail)
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let hovered = null;
  renderer.domElement.addEventListener('mousemove', (ev) => {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(nodeMeshes)[0];
    if (hit) {
      hovered = hit.object;
      tip.hidden = false;
      tip.textContent = hovered.userData.title;
      tip.style.left = (ev.clientX - rect.left + 14) + 'px';
      tip.style.top = (ev.clientY - rect.top + 14) + 'px';
      renderer.domElement.style.cursor = 'pointer';
      controls.autoRotate = false;
    } else {
      hovered = null; tip.hidden = true;
      renderer.domElement.style.cursor = 'grab';
      controls.autoRotate = true;
    }
  });
  renderer.domElement.addEventListener('click', () => {
    if (hovered && hovered.userData.href) window.open(hovered.userData.href, '_blank', 'noopener');
  });

  // type filter
  document.getElementById('globeFilters').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    document.querySelectorAll('#globeFilters button').forEach((x) => x.classList.toggle('on', x === b));
    const f = b.dataset.f;
    for (const m of nodeMeshes) {
      const vis = (f === 'all' || m.userData.type === f);
      m.visible = vis;
      if (m.userData._label) m.userData._label.visible = vis;
    }
    for (const line of edgeLines) {
      line.visible = byId[line.userData.source].visible && byId[line.userData.target].visible;
    }
  });

  // search highlight (dim non-matches)
  document.getElementById('globeSearch').addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    for (const m of nodeMeshes) {
      const n = m.userData;
      const match = !q || ((n.alias || '') + ' ' + (n.title || '')).toLowerCase().includes(q);
      m.material.opacity = match ? 1 : 0.12;
      if (n._label) n._label.element.style.opacity = match ? '1' : '0.12';
    }
  });

  function resize() {
    camera.aspect = W() / H(); camera.updateProjectionMatrix();
    renderer.setSize(W(), H()); labelRenderer.setSize(W(), H());
  }
  window.addEventListener('resize', resize);

  (function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
    labelRenderer.render(scene, camera);
  })();
})();
</script>
{% endblock %}
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_site_graph_routes.py -v`
Expected: PASS (all 3).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/templates/graph.html tests/unit/test_site_graph_routes.py
git commit -m "feat(site): 3D wireframe-globe graph (Three.js) replacing Cytoscape"
```

---

## Task 6: Backfill, browser-verify, docs

**Files:** Modify `CLAUDE.md`, `docs/ARCHITECTURE.md`.

- [ ] **Step 1: Backfill (re-embed + aliases + edges) on the real DB**

Run: `set -a; . config/atlas-chat.env; set +a; python -m aishelf.db sync --rebuild`
Expected: `synced: +N ...`, no errors. Confirm aliases populated:
```bash
python -c "
from aishelf.db import schema
from aishelf.db.config import default_db_path
con = schema.connect(default_db_path('data'))
print('with alias:', con.execute(\"SELECT COUNT(*) FROM items WHERE alias IS NOT NULL AND alias!=''\").fetchone()[0])
for r in con.execute('SELECT alias, title FROM items LIMIT 8'): print(' ', repr(r['alias']), '<-', r['title'][:40])
con.close()"
```

- [ ] **Step 2: Restart + browser-verify the globe**

Restart: `pkill -f aishelf.site; sleep 1; nohup bash scripts/run.sh > /tmp/atlas-site.log 2>&1 &`
Then verify with Playwright (no console errors, WebGL canvas present, labels rendered):
```bash
python3 -c "
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={'width':1440,'height':860})
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto('http://127.0.0.1:8001/graph', wait_until='networkidle'); pg.wait_for_timeout(4000)
    print('canvas:', pg.locator('#globe canvas').count(), '| labels:', pg.locator('.node-label').count())
    pg.screenshot(path='outputs/globe.png'); b.close()
print('errors:', errs or 'none')
" 2>&1 | grep -v SharedArrayBuffer
```
Expected: a WebGL canvas, >0 labels, no page errors. Eyeball `outputs/globe.png` for the wireframe sphere with nodes + arcs.

- [ ] **Step 3: Update CLAUDE.md**
- In `aishelf.db/`: note `load_graph` now returns per-node `alias` + PCA unit-sphere `x,y,z`.
- Add a package-root `aishelf/alias.py` mention (LLM short-alias client, `ATLAS_CHAT_*`).
- In `sync.py`: note it generates aliases (on title change) alongside embeddings/edges; one-time `sync --rebuild` backfills aliases.
- Update the `/graph` description to "3D Three.js wireframe-globe (nodes placed by PCA of embeddings, arcs for edges)".

- [ ] **Step 4: Update docs/ARCHITECTURE.md**
- `aishelf.db` table: `schema.py` gains `alias`; `graph.py` `load_graph` emits alias + positions; add `aishelf/alias.py` (package-root) row.
- Section 4 "Knowledge graph" bullet: nodes placed by read-time PCA of embeddings on a Three.js wireframe sphere; labels are LLM aliases (truncated-title fallback); arcs for edges.
- Note aliases in the one-time `sync --rebuild` backfill.
- Update the status header test count to `pytest -q | tail -1`.
- Design-history table row: `Knowledge graph 3D globe + aliases | 2026-06-15`.

- [ ] **Step 5: Full suite + commit**

Run: `pytest -q` (expect all pass; use the count in ARCHITECTURE.md).
```bash
git add CLAUDE.md docs/ARCHITECTURE.md
git commit -m "docs: document 3D globe graph + node aliases"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Wireframe-sphere look, nodes on surface, arcs, rotate/zoom → Task 5 ✓
- Node placement via PCA of embeddings (read-time), hash fallback <3/none → Task 4 ✓
- LLM ≤8-char aliases, stored, on title change, truncated-title fallback → Tasks 1–3, 5 (frontend fallback) ✓
- `alias.py` at package root (no db→site) → Task 2 ✓
- `/api/graph` additive (alias + x,y,z), edges unchanged → Task 4 ✓
- Click→detail, hover→full title, type filter, search highlight, empty state → Task 5 ✓
- Degradation (alias off→truncate; no embed→hash; empty→state) → Tasks 2/3/4/5 ✓
- Backfill via `sync --rebuild`; docs → Task 6 ✓

**Placeholder scan:** none — every code/test step is complete.

**Type consistency:** `alias.generate_aliases(pairs) -> list[str]|None` (Task 2) called in `sync` (Task 3) and not elsewhere; `_hash_point(id)->tuple` / `_sphere_positions(node_ids, groups)->dict` (Task 4) used in `load_graph` (Task 4); `load_graph` node shape `{id,type,title,alias,degree,x,y,z}` (Task 4) consumed by `graph.html` (reads `n.id/n.alias/n.title/n.type/n.degree/n.x/n.y/n.z`, Task 5) and asserted by tests; `existing` tuple widened to 5 fields consistently within `sync` (Task 3). `_load_groups` (existing) reused by `_sphere_positions` via `load_graph`.
```

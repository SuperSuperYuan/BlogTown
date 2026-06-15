# Knowledge Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/graph` page that renders the content library as an interactive semantic graph — nodes = content items (click → detail page), edges = embedding cosine similarity — backed by a precomputed `edges` table updated incrementally at sync.

**Architecture:** Reuse the per-item embeddings already in `atlas.db`. A new `edges` table stores the full threshold graph (every pair with cosine ≥ `GRAPH_SIM_FLOOR`, stored once canonically with `src < dst`). `db/graph.py` owns edge computation (pure cosine + DB ops) and a read-side `load_graph` that caps each node to its top-K strongest edges. `sync` updates edges incrementally for (re)embedded items and drops edges of pruned items. A read-only `GET /api/graph` serves JSON; `GET /graph` renders a Cytoscape.js page.

**Tech Stack:** Python 3.11+, SQLite (stdlib), numpy (cosine), FastAPI + Jinja2, Cytoscape.js + fcose (CDN, frontend), pytest.

**Spec:** `docs/superpowers/specs/2026-06-11-knowledge-graph-design.md`

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/aishelf/db/schema.py` | Modify | Add the `edges` table to `SCHEMA_SQL`. |
| `src/aishelf/db/__main__.py` | Modify | `--rebuild` also drops `edges`. |
| `src/aishelf/db/graph.py` | Create | Pure cosine + `neighbors`; DB ops `recompute_edges_for`/`delete_edges_for`; read-side `load_graph` (top-K cap + degree). |
| `src/aishelf/db/sync.py` | Modify | After embedding writes, recompute edges for (re)embedded ids; drop edges for pruned ids. |
| `src/aishelf/site/app.py` | Modify | `GET /graph` (page) + `GET /api/graph` (JSON). |
| `src/aishelf/site/templates/graph.html` | Create | Cytoscape.js graph page (extends base.html). |
| `src/aishelf/site/templates/base.html` | Modify | Add 「图谱」 nav link. |
| `CLAUDE.md`, `docs/ARCHITECTURE.md` | Modify | Document the graph + `edges` table + one-time `sync --rebuild` backfill. |
| `tests/unit/test_db_graph.py` | Create | Pure + DB graph tests. |
| `tests/unit/test_db_sync.py` | Modify | Edge-update-on-sync tests. |
| `tests/unit/test_site_graph_routes.py` | Create | `/graph` + `/api/graph` route tests. |

Constants live in `db/graph.py`: `GRAPH_SIM_FLOOR = 0.5`, `GRAPH_TOP_K = 8`. All graph functions take `floor` / `cap_k` params (defaulting to the constants) so tests pass explicit values and stay robust if the constants are tuned (Task 8).

---

## Task 1: `edges` table + drop on rebuild

**Files:**
- Modify: `src/aishelf/db/schema.py`
- Modify: `src/aishelf/db/__main__.py:34`
- Test: `tests/unit/test_db_graph.py` (create with this one test for now)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_db_graph.py`:

```python
from aishelf.db import schema


def test_edges_table_created(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    names = {r["name"] for r in con.execute("PRAGMA table_info(edges)")}
    con.close()
    assert names == {"src", "dst", "weight"}
```

- [ ] **Step 2: Run it — verify fail**

Run: `pytest tests/unit/test_db_graph.py::test_edges_table_created -v`
Expected: FAIL — no `edges` table (PRAGMA returns nothing).

- [ ] **Step 3: Add the table**

In `src/aishelf/db/schema.py`, append the `edges` table to `SCHEMA_SQL` (after the `items_fts` virtual table, before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS edges (
  src    TEXT NOT NULL,
  dst    TEXT NOT NULL,
  weight REAL NOT NULL,
  PRIMARY KEY (src, dst)
);
```

- [ ] **Step 4: Drop edges on rebuild**

In `src/aishelf/db/__main__.py`, change the rebuild drop line (currently dropping `items` and `items_fts`) to also drop `edges`:

```python
            con.executescript(
                "DROP TABLE IF EXISTS items; "
                "DROP TABLE IF EXISTS items_fts; "
                "DROP TABLE IF EXISTS edges;"
            )
```

- [ ] **Step 5: Run it — verify pass**

Run: `pytest tests/unit/test_db_graph.py::test_edges_table_created -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/db/schema.py src/aishelf/db/__main__.py tests/unit/test_db_graph.py
git commit -m "feat(db): add edges table for the knowledge graph"
```

---

## Task 2: Pure cosine + neighbors (`db/graph.py`)

**Files:**
- Create: `src/aishelf/db/graph.py`
- Test: `tests/unit/test_db_graph.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_db_graph.py`:

```python
import numpy as np

from aishelf.db import graph


def test_neighbors_threshold_sorted_and_excludes_self():
    ids = ["a", "b", "c"]
    mat = np.array([[1.0, 0.0], [0.96, 0.28], [0.0, 1.0]], dtype=np.float32)  # a~b high, a~c 0
    out = graph.neighbors([1.0, 0.0], ids, mat, floor=0.5, exclude="a")
    assert [i for i, _ in out] == ["b"]          # c below floor, a excluded
    assert out[0][1] > 0.9


def test_neighbors_empty():
    assert graph.neighbors([1.0, 0.0], [], np.empty((0, 2), dtype=np.float32), floor=0.5) == []


def test_canon_orders_pair():
    assert graph._canon("b", "a") == ("a", "b")
    assert graph._canon("a", "b") == ("a", "b")
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_db_graph.py -k "neighbors or canon" -v`
Expected: FAIL — `graph` module / functions undefined.

- [ ] **Step 3: Create the module with pure helpers**

Create `src/aishelf/db/graph.py`:

```python
"""Semantic knowledge graph over the content library.

Nodes are content items; edges are embedding cosine similarity. Storage keeps
the full threshold graph (every pair with cosine >= GRAPH_SIM_FLOOR, stored once
canonically with src < dst). The read side (load_graph) caps each node to its
top-K strongest edges so a dense, all-AI corpus does not render as a hairball.
Edges are recomputed incrementally at sync time.
"""

from __future__ import annotations

import numpy as np

from aishelf.db import schema, vector

GRAPH_SIM_FLOOR = 0.5
GRAPH_TOP_K = 8


def _sims(vec, matrix: np.ndarray) -> np.ndarray:
    """Cosine of `vec` against every row of `matrix` (shape (N,)). Empty -> empty."""
    if matrix.shape[0] == 0:
        return np.empty((0,), dtype=np.float32)
    q = np.asarray(vec, dtype=np.float32)
    qn = float(np.linalg.norm(q))
    if qn == 0.0:
        return np.zeros(matrix.shape[0], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1)
    return (matrix @ q) / (norms * qn + 1e-12)


def neighbors(vec, ids: list[str], matrix: np.ndarray, *, floor: float = GRAPH_SIM_FLOOR,
              exclude: str | None = None) -> list[tuple[str, float]]:
    """(id, sim) pairs with sim >= floor, sorted desc, excluding `exclude`."""
    sims = _sims(vec, matrix)
    out = []
    for i, sid in enumerate(ids):
        if sid == exclude:
            continue
        s = float(sims[i])
        if s >= floor:
            out.append((sid, s))
    out.sort(key=lambda t: -t[1])
    return out


def _canon(a: str, b: str) -> tuple[str, str]:
    """Canonical undirected key: (min, max) by string order."""
    return (a, b) if a < b else (b, a)
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_db_graph.py -k "neighbors or canon" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/graph.py tests/unit/test_db_graph.py
git commit -m "feat(db): graph cosine neighbors + canonical edge key"
```

---

## Task 3: DB edge ops — recompute / delete (`db/graph.py`)

**Files:**
- Modify: `src/aishelf/db/graph.py`
- Test: `tests/unit/test_db_graph.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_db_graph.py`:

```python
def _seed_item(con, rid, typ, vec):
    con.execute(
        "INSERT INTO items (id, type, title, author, platform, source_url, "
        "published_at, collected_at, summary, keywords, embedding, embedding_model, "
        "embedding_dim, content_hash, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, typ, f"标题{rid}", "作者", "p", f"https://x/{rid}", "2024-01-01",
         "2024-01-02", "s", "[]", graph.vector.pack(vec), "m", len(vec), "h", "2024-01-02"),
    )


def _edge_set(con):
    return {(r["src"], r["dst"]) for r in con.execute("SELECT src, dst FROM edges")}


def test_recompute_edges_for_new_item(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0])
    _seed_item(con, "b", "blog", [0.97, 0.24])   # close to a
    _seed_item(con, "c", "video", [0.0, 1.0])    # far from a
    graph.recompute_edges_for(con, ["a", "b", "c"], floor=0.5)
    assert _edge_set(con) == {("a", "b")}        # only a-b clears the floor, stored canonically
    con.close()


def test_recompute_is_incremental_and_symmetric(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0])
    graph.recompute_edges_for(con, ["a"], floor=0.5)      # no neighbors yet
    assert _edge_set(con) == set()
    _seed_item(con, "b", "blog", [0.97, 0.24])
    graph.recompute_edges_for(con, ["b"], floor=0.5)      # adding b links a-b
    assert _edge_set(con) == {("a", "b")}
    con.close()


def test_delete_edges_for_removes_incident(tmp_path):
    con = schema.connect(tmp_path / "atlas.db")
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0])
    _seed_item(con, "b", "blog", [0.97, 0.24])
    graph.recompute_edges_for(con, ["a", "b"], floor=0.5)
    graph.delete_edges_for(con, ["b"])
    assert _edge_set(con) == set()
    con.close()
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_db_graph.py -k "recompute or delete_edges" -v`
Expected: FAIL — `recompute_edges_for` / `delete_edges_for` undefined.

- [ ] **Step 3: Implement the DB ops**

Append to `src/aishelf/db/graph.py`:

```python
def _load_groups(con) -> dict[int, tuple[list[str], np.ndarray]]:
    """All stored embeddings grouped by dimension: {dim: (ids, matrix)}.

    Grouping by dim keeps a stale, different-dimension vector (after a model
    change, before a re-sync) from ever being compared against the current one.
    """
    rows = con.execute(
        "SELECT id, embedding, embedding_dim FROM items WHERE embedding IS NOT NULL"
    ).fetchall()
    by_dim: dict[int, list[tuple[str, bytes]]] = {}
    for r in rows:
        by_dim.setdefault(r["embedding_dim"], []).append((r["id"], r["embedding"]))
    groups: dict[int, tuple[list[str], np.ndarray]] = {}
    for dim, items in by_dim.items():
        ids = [i for i, _ in items]
        mat = np.stack([vector.unpack(b) for _, b in items])
        groups[dim] = (ids, mat)
    return groups


def delete_edges_for(con, item_ids) -> None:
    """Drop every edge incident to any of the given ids."""
    for cid in item_ids:
        con.execute("DELETE FROM edges WHERE src = ? OR dst = ?", (cid, cid))


def recompute_edges_for(con, item_ids, *, floor: float = GRAPH_SIM_FLOOR) -> None:
    """Recompute edges for the given (re)embedded items.

    Deletes each id's incident edges, then re-adds its >= floor neighbors (within
    the same embedding dimension). Symmetric + order-independent: an edge a-b is
    present whenever either endpoint's recompute adds it.
    """
    item_ids = list(item_ids)
    if not item_ids:
        return
    delete_edges_for(con, item_ids)
    groups = _load_groups(con)
    pos: dict[str, tuple[int, int]] = {}
    for dim, (ids, _mat) in groups.items():
        for i, sid in enumerate(ids):
            pos[sid] = (dim, i)
    for cid in item_ids:
        loc = pos.get(cid)
        if loc is None:               # item has no embedding -> no edges
            continue
        dim, i = loc
        ids, mat = groups[dim]
        for oid, sim in neighbors(mat[i], ids, mat, floor=floor, exclude=cid):
            src, dst = _canon(cid, oid)
            con.execute(
                "INSERT OR REPLACE INTO edges (src, dst, weight) VALUES (?, ?, ?)",
                (src, dst, sim),
            )
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_db_graph.py -k "recompute or delete_edges" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/graph.py tests/unit/test_db_graph.py
git commit -m "feat(db): incremental recompute/delete of graph edges"
```

---

## Task 4: Read the graph with top-K cap (`db/graph.py`)

**Files:**
- Modify: `src/aishelf/db/graph.py`
- Test: `tests/unit/test_db_graph.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_db_graph.py`:

```python
def test_load_graph_shape_and_degree(tmp_path):
    db = tmp_path / "atlas.db"
    con = schema.connect(db)
    schema.init_db(con)
    _seed_item(con, "a", "video", [1.0, 0.0])
    _seed_item(con, "b", "blog", [0.97, 0.24])
    graph.recompute_edges_for(con, ["a", "b"], floor=0.5)
    con.commit(); con.close()
    g = graph.load_graph(db, cap_k=8)
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"a", "b"}
    a = next(n for n in g["nodes"] if n["id"] == "a")
    assert a["type"] == "video" and a["title"] == "标题a" and a["degree"] == 1
    assert g["edges"] == [{"source": "a", "target": "b", "weight": g["edges"][0]["weight"]}]
    assert g["edges"][0]["weight"] > 0.9


def test_load_graph_caps_top_k(tmp_path):
    db = tmp_path / "atlas.db"
    con = schema.connect(db)
    schema.init_db(con)
    # hub "h" connects to 3 leaves with descending weights; cap_k=2 keeps the 2 strongest
    con.execute("INSERT INTO edges (src, dst, weight) VALUES ('h','l1',0.9)")
    con.execute("INSERT INTO edges (src, dst, weight) VALUES ('h','l2',0.8)")
    con.execute("INSERT INTO edges (src, dst, weight) VALUES ('h','l3',0.6)")
    for rid in ("h", "l1", "l2", "l3"):
        _seed_item(con, rid, "blog", [1.0, 0.0])
    con.commit(); con.close()
    g = graph.load_graph(db, cap_k=2)
    kept = {(e["source"], e["target"]) for e in g["edges"]}
    assert ("h", "l1") in kept and ("h", "l2") in kept and ("h", "l3") not in kept


def test_load_graph_empty(tmp_path):
    db = tmp_path / "atlas.db"
    con = schema.connect(db); schema.init_db(con); con.close()
    assert graph.load_graph(db) == {"nodes": [], "edges": []}
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_db_graph.py -k load_graph -v`
Expected: FAIL — `load_graph` undefined.

- [ ] **Step 3: Implement `load_graph`**

Append to `src/aishelf/db/graph.py`:

```python
def load_graph(db_path, *, cap_k: int = GRAPH_TOP_K) -> dict:
    """Nodes (id/type/title/author + degree) and edges, capping each node to its
    top-K strongest incident edges (an edge survives if it is in the top-K of
    either endpoint). Degree counts the kept edges."""
    con = schema.connect(db_path)
    try:
        schema.init_db(con)
        node_rows = con.execute("SELECT id, type, title, author FROM items").fetchall()
        edge_rows = con.execute("SELECT src, dst, weight FROM edges").fetchall()
    finally:
        con.close()

    incident: dict[str, list[tuple[float, str, str]]] = {}
    wmap: dict[tuple[str, str], float] = {}
    for r in edge_rows:
        wmap[(r["src"], r["dst"])] = r["weight"]
        incident.setdefault(r["src"], []).append((r["weight"], r["src"], r["dst"]))
        incident.setdefault(r["dst"], []).append((r["weight"], r["src"], r["dst"]))

    keep: set[tuple[str, str]] = set()
    for _nid, lst in incident.items():
        lst.sort(key=lambda t: -t[0])
        for _w, s, d in lst[:cap_k]:
            keep.add((s, d))

    degree: dict[str, int] = {}
    edges = []
    for (s, d) in keep:
        edges.append({"source": s, "target": d, "weight": wmap[(s, d)]})
        degree[s] = degree.get(s, 0) + 1
        degree[d] = degree.get(d, 0) + 1

    nodes = [
        {"id": r["id"], "type": r["type"], "title": r["title"],
         "author": r["author"], "degree": degree.get(r["id"], 0)}
        for r in node_rows
    ]
    return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_db_graph.py -v`
Expected: PASS (all graph tests)

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/graph.py tests/unit/test_db_graph.py
git commit -m "feat(db): load_graph with per-node top-K cap and degree"
```

---

## Task 5: Update edges during `sync`

**Files:**
- Modify: `src/aishelf/db/sync.py`
- Test: `tests/unit/test_db_sync.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_db_sync.py` (the file already imports `json`, `from aishelf import embed`, `from aishelf.db import schema, vector`, `from aishelf.db.sync import sync`, and defines `_write_video`/`_embedding_row` from the embeddings work — reuse them; add `from aishelf.db import graph`):

```python
from aishelf.db import graph as _graph


def _edges(db_path):
    con = schema.connect(db_path)
    rows = {(r["src"], r["dst"]) for r in con.execute("SELECT src, dst FROM edges")}
    con.close()
    return rows


def test_sync_builds_edges_for_similar_items(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    _write_video(data, "v2")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    # v1 and v2 get near-identical vectors -> should be linked
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0], [0.98, 0.2]][: len(texts)])
    monkeypatch.setattr(_graph, "GRAPH_SIM_FLOOR", 0.5)
    sync(data, db)
    assert _edges(db) == {("v1", "v2")}


def test_sync_no_edges_when_embeddings_unconfigured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    _write_video(data, "v2")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    sync(data, db)
    assert _edges(db) == set()


def test_sync_drops_edges_for_removed_item(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    _write_video(data, "v2")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0], [0.98, 0.2]][: len(texts)])
    monkeypatch.setattr(_graph, "GRAPH_SIM_FLOOR", 0.5)
    sync(data, db)
    assert _edges(db) == {("v1", "v2")}
    (data / "videos" / "v2.json").unlink()   # delete one item's file
    sync(data, db)
    assert _edges(db) == set()                # its edge is gone
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_db_sync.py -k "edges" -v`
Expected: FAIL — `sync` does not touch the `edges` table yet (sets stay empty / not dropped).

- [ ] **Step 3: Wire edge updates into `sync`**

In `src/aishelf/db/sync.py`:

(a) add `graph` to the db import:

```python
from aishelf.db import schema, tokenize, vector, graph
```

(b) Track which ids were embedded this run, then update edges after the prune. Replace the embedding-write block and the prune block (current lines 141–160) with:

```python
        embedded_ids: list[str] = []
        if to_embed and embed_model:
            vectors = embed.embed_texts([_embed_text(it, note) for it, note in to_embed])
            if vectors and len(vectors) == len(to_embed):
                for (it, _note), vec in zip(to_embed, vectors):
                    con.execute(
                        "UPDATE items SET embedding=?, embedding_model=?, embedding_dim=? "
                        "WHERE id=?",
                        (vector.pack(vec), embed_model, len(vec), it.id),
                    )
                    embedded_ids.append(it.id)
            elif vectors:
                logger.warning(
                    "embed_texts returned %d vectors for %d texts; skipping embedding update",
                    len(vectors), len(to_embed),
                )

        stale = [i for i in existing if i not in seen]
        for rid in stale:
            con.execute("DELETE FROM items WHERE id = ?", (rid,))
            con.execute("DELETE FROM items_fts WHERE item_id = ?", (rid,))
        summary.removed = len(stale)

        # Knowledge-graph edges: drop pruned items' edges, recompute changed items'
        # edges against the post-prune embedding set.
        if stale:
            graph.delete_edges_for(con, stale)
        if embedded_ids:
            graph.recompute_edges_for(con, embedded_ids)
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/unit/test_db_sync.py -v`
Expected: PASS (new edge tests + all pre-existing sync tests)

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/sync.py tests/unit/test_db_sync.py
git commit -m "feat(db): sync updates knowledge-graph edges incrementally"
```

---

## Task 6: `/graph` page + `/api/graph` JSON + nav link

**Files:**
- Modify: `src/aishelf/site/app.py`
- Modify: `src/aishelf/site/templates/base.html:12`
- Test: `tests/unit/test_site_graph_routes.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_graph_routes.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    (tmp_path / "videos").mkdir(parents=True)
    rec = {"id": "v1", "type": "video", "title": "大模型", "author": "作者甲",
           "platform": "youtube", "source_url": "https://x/v1", "published_at": "2024-01-01",
           "summary": "摘要", "keywords": [], "collected_at": "2024-01-02T00:00:00",
           "thumbnail_url": "https://img/x.jpg"}
    (tmp_path / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")     # no ATLAS_EMBED_* -> nodes, no edges
    from aishelf.site.app import app
    return TestClient(app)


def test_api_graph_shape(client):
    r = client.get("/api/graph")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"nodes", "edges"}
    assert any(n["id"] == "v1" and n["type"] == "video" and "degree" in n for n in body["nodes"])
    assert body["edges"] == []     # no embeddings configured in tests -> no edges


def test_graph_page_renders(client):
    r = client.get("/graph")
    assert r.status_code == 200
    assert "/api/graph" in r.text
    assert "cytoscape" in r.text
    assert 'id="cy"' in r.text


def test_nav_has_graph_link(client):
    r = client.get("/")
    assert 'href="/graph"' in r.text
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/unit/test_site_graph_routes.py -v`
Expected: FAIL — routes / nav link / template missing (404 + assertion errors).

- [ ] **Step 3: Add the routes**

In `src/aishelf/site/app.py`, add `graph` to the db imports (next to `from aishelf.db import search as db_search`):

```python
from aishelf.db import graph as db_graph
```

Add the routes (place next to the other page/api routes, e.g. after the `/ask` routes):

```python
@app.get("/graph", response_class=HTMLResponse)
def graph_page(request: Request):
    return templates.TemplateResponse(request, "graph.html", {})


@app.get("/api/graph")
def api_graph():
    """Read-only semantic graph (nodes + top-K-capped edges) over the derived DB."""
    return db_graph.load_graph(default_db_path(get_data_dir()))
```

- [ ] **Step 4: Add the nav link**

In `src/aishelf/site/templates/base.html`, add a 图谱 link in the `<nav>` (line 12), after the 问答 link:

```html
    <nav><a href="/videos">视频</a><a href="/blogs">博客</a><a href="/ask">问答</a><a href="/graph">图谱</a><a href="/collect">Hermes</a></nav>
```

(The `graph.html` template is created in Task 7; this task's `test_graph_page_renders` stays red until then — that is expected; run only the api/nav tests here.)

- [ ] **Step 5: Run the API + nav tests**

Run: `pytest tests/unit/test_site_graph_routes.py -k "api_graph or nav" -v`
Expected: PASS (2 tests). `test_graph_page_renders` still fails until Task 7.

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/base.html tests/unit/test_site_graph_routes.py
git commit -m "feat(site): /api/graph endpoint + /graph route + nav link"
```

---

## Task 7: Cytoscape graph page (`graph.html`)

**Files:**
- Create: `src/aishelf/site/templates/graph.html`
- Test: `tests/unit/test_site_graph_routes.py::test_graph_page_renders` (already written in Task 6)

- [ ] **Step 1: Confirm the test is red**

Run: `pytest tests/unit/test_site_graph_routes.py::test_graph_page_renders -v`
Expected: FAIL — `graph.html` does not exist (TemplateNotFound / 500).

- [ ] **Step 2: Create the template**

Create `src/aishelf/site/templates/graph.html`:

```html
{% extends "base.html" %}
{% block title %}图谱 · Atlas{% endblock %}
{% block content %}
<div class="graph-wrap">
  <div class="graph-bar">
    <span class="graph-title">知识图谱</span>
    <span class="graph-hint">语义相似度连接 · 点击节点进入详情</span>
    <span class="graph-spacer"></span>
    <input id="graphSearch" class="graph-search" placeholder="高亮标题…" />
    <div class="graph-filters" id="graphFilters">
      <button type="button" data-f="all" class="on">全部</button>
      <button type="button" data-f="video">视频</button>
      <button type="button" data-f="blog">博客</button>
    </div>
  </div>
  <div id="cy" class="graph-canvas"></div>
  <div id="graphEmpty" class="graph-empty" hidden>
    图谱暂时没有数据。先在 <a href="/collect">Hermes</a> 采集内容，配置好 embedding 服务后运行一次
    <code>python -m aishelf.db sync --rebuild</code>。
  </div>
</div>
<style>
  main:has(.graph-wrap) { max-width: none; padding: 0; }
  .graph-wrap { position: relative; display: flex; flex-direction: column; height: calc(100vh - 57px); height: calc(100dvh - 57px); }
  .graph-bar { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid #e6ecf4; background: #fff; flex: none; }
  .graph-title { font-weight: 700; color: #11203a; }
  .graph-hint { font-size: 12px; color: #9aa6bb; }
  .graph-spacer { margin-left: auto; }
  .graph-search { height: 32px; border: 1px solid #e6ecf4; border-radius: 8px; padding: 0 10px; font-size: 13px; outline: none; }
  .graph-search:focus { border-color: #478eff; box-shadow: 0 0 0 3px #eaf2ff; }
  .graph-filters button { height: 30px; padding: 0 12px; margin-left: 6px; border: 1px solid #e6ecf4; background: #f5f8fd; color: #5b6a82; border-radius: 999px; cursor: pointer; font-size: 13px; }
  .graph-filters button.on { background: #478eff; border-color: #478eff; color: #fff; }
  .graph-canvas { flex: 1; min-height: 0; background: radial-gradient(900px 600px at 30% 18%, #eef4ff, #e8eef6); }
  .graph-empty { position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); max-width: 460px; text-align: center; color: #5b6a82; font-size: 14px; line-height: 1.7; }
  .graph-empty code { background: #eef2f7; padding: 2px 6px; border-radius: 6px; }
</style>
<script src="https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js"></script>
<script src="https://unpkg.com/layout-base@2.0.1/layout-base.js"></script>
<script src="https://unpkg.com/cose-base@2.2.0/cose-base.js"></script>
<script src="https://unpkg.com/cytoscape-fcose@2.2.0/cytoscape-fcose.js"></script>
<script>
(async function () {
  let data;
  try { data = await (await fetch('/api/graph')).json(); }
  catch (e) { data = { nodes: [], edges: [] }; }

  if (!data.nodes || !data.nodes.length) {
    document.getElementById('graphEmpty').hidden = false;
    return;
  }

  const COLOR = { video: '#f0883e', blog: '#478eff' };
  const elements = [];
  for (const n of data.nodes) {
    elements.push({ data: {
      id: n.id, label: n.title, type: n.type, deg: n.degree || 0,
      href: (n.type === 'video' ? '/videos/' : '/blogs/') + encodeURIComponent(n.id),
    }});
  }
  for (const e of data.edges) {
    elements.push({ data: { id: e.source + '__' + e.target, source: e.source, target: e.target, weight: e.weight } });
  }

  // Prefer fcose (cluster layout); fall back to built-in cose if the extension didn't load.
  let layout = { name: 'cose', animate: true, idealEdgeLength: 90, padding: 30 };
  try {
    if (window.cytoscapeFcose) {
      cytoscape.use(window.cytoscapeFcose);
      layout = { name: 'fcose', animate: true, randomize: true, nodeRepulsion: 6000, idealEdgeLength: 90, padding: 30 };
    }
  } catch (e) { /* keep cose */ }

  const cy = cytoscape({
    container: document.getElementById('cy'),
    elements,
    layout,
    style: [
      { selector: 'node', style: {
        'background-color': (ele) => COLOR[ele.data('type')] || '#9aa6bb',
        'label': 'data(label)', 'font-size': 9, 'color': '#11203a',
        'text-wrap': 'ellipsis', 'text-max-width': 120, 'text-valign': 'bottom', 'text-margin-y': 3,
        'width': (ele) => 14 + 3 * Math.min(ele.data('deg'), 8),
        'height': (ele) => 14 + 3 * Math.min(ele.data('deg'), 8),
        'border-width': 2, 'border-color': '#fff' } },
      { selector: 'edge', style: {
        'width': (ele) => 1 + 3 * Math.max(0, (ele.data('weight') || 0.5) - 0.4),
        'line-color': '#9fc3ff', 'opacity': 0.55, 'curve-style': 'straight' } },
      { selector: '.dim', style: { 'opacity': 0.12 } },
      { selector: '.hi', style: { 'border-color': '#ff34d6', 'border-width': 4 } },
    ],
  });

  // Click a node -> open its detail page in a new tab.
  cy.on('tap', 'node', (evt) => {
    const href = evt.target.data('href');
    if (href) window.open(href, '_blank', 'noopener');
  });

  // Type filter.
  document.getElementById('graphFilters').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    document.querySelectorAll('#graphFilters button').forEach((x) => x.classList.toggle('on', x === b));
    const f = b.dataset.f;
    cy.nodes().forEach((n) => n.style('display', (f === 'all' || n.data('type') === f) ? 'element' : 'none'));
    cy.edges().forEach((ed) => ed.style('display',
      (ed.source().style('display') !== 'none' && ed.target().style('display') !== 'none') ? 'element' : 'none'));
  });

  // Search highlight.
  document.getElementById('graphSearch').addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    cy.batch(() => {
      cy.elements().removeClass('dim hi');
      if (!q) return;
      const match = cy.nodes().filter((n) => (n.data('label') || '').toLowerCase().includes(q));
      if (!match.length) return;
      cy.elements().addClass('dim');
      match.removeClass('dim').addClass('hi');
      match.neighborhood().removeClass('dim');
    });
  });
})();
</script>
{% endblock %}
```

- [ ] **Step 3: Run — verify pass**

Run: `pytest tests/unit/test_site_graph_routes.py -v`
Expected: PASS (all 3, including `test_graph_page_renders`)

- [ ] **Step 4: Commit**

```bash
git add src/aishelf/site/templates/graph.html
git commit -m "feat(site): Cytoscape knowledge-graph page"
```

---

## Task 8: Backfill + calibrate thresholds

**Files:**
- Modify: `src/aishelf/db/graph.py` (constants only, if calibration warrants)

- [ ] **Step 1: Backfill edges on the real DB**

The `edges` table is empty on existing DBs until something re-syncs. Populate it (this also re-embeds + rebuilds the graph from the real corpus):

Run: `set -a; . config/atlas-chat.env; set +a; python -m aishelf.db sync --rebuild`
Expected: `synced: +N ...`; no errors.

- [ ] **Step 2: Inspect the pairwise-cosine distribution**

Run:

```bash
python - <<'PY'
import numpy as np
from aishelf.db import schema, graph
from aishelf.db.config import default_db_path
con = schema.connect(default_db_path("data")); schema.init_db(con)
groups = graph._load_groups(con); con.close()
ids, mat = next(iter(groups.values()))
n = len(ids); sims = []
for i in range(n):
    s = graph._sims(mat[i], mat)
    for j in range(i+1, n):
        sims.append(float(s[j]))
sims = np.array(sims)
for p in (50, 75, 90, 95, 99):
    print(f"p{p}: {np.percentile(sims, p):.3f}")
print("max:", sims.max().round(3), "count>=0.5:", int((sims>=0.5).sum()), "of", len(sims))
PY
```

- [ ] **Step 3: Set the constants**

Pick `GRAPH_SIM_FLOOR` so the graph is connected but not a hairball — a good heuristic is around the **p85–p90** of the distribution (so ~10–15% of pairs become edges). If `count>=0.5` is already small (a sparse graph) keep `0.5`; if nearly every pair is ≥0.5 (hairball), raise the floor to the p90 value. Edit `src/aishelf/db/graph.py`:

```python
GRAPH_SIM_FLOOR = 0.5   # <- set to the calibrated value from Step 2
GRAPH_TOP_K = 8         # <- raise/lower if nodes look too sparse/dense after render
```

- [ ] **Step 4: Re-sync and eyeball**

Run: `set -a; . config/atlas-chat.env; set +a; python -m aishelf.db sync --rebuild`
Then load `http://127.0.0.1:8001/graph` (restart the site if running) and confirm clusters look reasonable (related items group; no single hairball; few orphan nodes).

- [ ] **Step 5: Commit (if constants changed)**

```bash
git add src/aishelf/db/graph.py
git commit -m "chore(graph): calibrate GRAPH_SIM_FLOOR/TOP_K to the corpus"
```

---

## Task 9: Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update CLAUDE.md**

- In the `aishelf.db/` architecture bullet, add `graph.py` (semantic edges: `neighbors`, `recompute_edges_for`/`delete_edges_for`, `load_graph` with top-K cap) and note the `edges` table in `schema.py`.
- Note that `sync` updates `edges` incrementally and that **a one-time `python -m aishelf.db sync --rebuild` is required to backfill `edges` on an existing DB** (same as the `note`/embedding rollouts).
- In the routes/site description, add `GET /graph` (Cytoscape page) and `GET /api/graph` (read-only nodes+edges JSON).

- [ ] **Step 2: Update docs/ARCHITECTURE.md**

- Add `aishelf/db/graph.py` and the `edges` table to the `aishelf.db` component table.
- Add `GET /graph` and `GET /api/graph` to the routes table.
- Add a "Knowledge graph" bullet to section 4 (flows): edges = embedding cosine ≥ floor, stored canonically, recomputed incrementally at sync; `/graph` renders them with Cytoscape, top-K capped at read time; nodes link to detail pages.
- Note the one-time `sync --rebuild` backfill and that the graph is empty without embeddings.
- Update the test count in the status header to what `pytest -q | tail -1` reports.
- Add a row to the design-history table: `Knowledge graph | 2026-06-15`.

- [ ] **Step 3: Verify the full suite**

Run: `pytest -q`
Expected: all pass; capture the count for ARCHITECTURE.md.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/ARCHITECTURE.md
git commit -m "docs: document the knowledge graph (/graph, edges table, sync)"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Node = item, click → detail page → Task 7 (`href` to `/videos|/blogs/{id}`) ✓
- Edge = embedding cosine → Tasks 2–3 ✓
- Stored `edges` table, canonical `src<dst` → Tasks 1, 3 ✓
- Incremental update at sync; delete on prune; full rebuild → Task 5 + Task 1 (drop on `--rebuild`) ✓
- Two-layer model (threshold storage + top-K display cap) → Task 3 (store all ≥floor) + Task 4 (`load_graph` cap) ✓
- Calibrated thresholds → Task 8 ✓
- Cytoscape page, color by type, size by degree, type filter, search highlight, empty state → Task 7 ✓
- `/api/graph` JSON + nav link → Task 6 ✓
- Resilience: no embeddings → empty edges (Task 5 test), items without embedding excluded from edges but still nodes (Task 4 / load_graph reads all item rows), dim mismatch via `_load_groups` grouping (Task 3) ✓
- Docs + backfill note → Task 9 + Task 8 ✓

**Placeholder scan:** none — every code/test step is complete.

**Type consistency:** `neighbors(vec, ids, matrix, *, floor, exclude)` (Task 2) used by `recompute_edges_for` (Task 3); `_canon` (Task 2) used in Task 3; `recompute_edges_for(con, ids, *, floor)` / `delete_edges_for(con, ids)` (Task 3) called in `sync` (Task 5); `load_graph(db_path, *, cap_k)` returning `{"nodes":[{id,type,title,author,degree}], "edges":[{source,target,weight}]}` (Task 4) consumed by `/api/graph` (Task 6) and `graph.html` (Task 7, reads `n.id/n.title/n.type/n.degree`, `e.source/e.target/e.weight`). `_load_groups` used by Task 3 and Task 8 calibration.

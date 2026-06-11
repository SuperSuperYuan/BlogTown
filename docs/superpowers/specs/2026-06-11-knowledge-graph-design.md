# Knowledge Graph — semantic graph of the content library

**Date:** 2026-06-11
**Status:** Design (approved, pre-plan)
**Scope:** A new `/graph` page that renders the whole content library as an
interactive semantic graph: nodes = content items, edges = embedding similarity.
Built on the existing embeddings (`text-embedding-v4`, 1024-dim) already stored
in `atlas.db`.

## Problem

Atlas can browse, search, and answer questions over the library, but there is no
way to *see* how the collected items relate to each other. A knowledge graph
makes the structure of the library visible — clusters of related talks/articles,
bridges between topics — and turns "what's in here and how does it connect" into
a single glance. Each node links straight to its detail page.

We already have per-item embeddings (the `/ask` hybrid retrieval feature), so
semantic similarity between items is essentially free to compute. That is the
edge signal.

## Decisions (locked)

- **Node = one content item** (video or blog). Clicking a node navigates to its
  detail page (`/videos/{id}` or `/blogs/{id}`).
- **Edge = embedding cosine similarity.** Two items are linked when their vectors
  are similar enough; edge weight = the cosine value.
- **Precomputed, stored edges**, incrementally updated at `sync` time (not
  computed per request). A new `edges` table in `atlas.db` (a derived view).
- **Frontend: Cytoscape.js** (via CDN) with the `fcose` force-directed clustering
  layout. Nodes colored by type, click → detail page, hover → title; plus a type
  filter and a search-highlight box.
- **Two-layer edge model:** storage keeps the full threshold graph (every pair
  with cosine ≥ `GRAPH_SIM_FLOOR`); the read/API layer caps each node to its
  top-K strongest edges (`GRAPH_TOP_K`) to avoid a hairball in the all-AI corpus.
- **Thresholds calibrated against real data.** `GRAPH_SIM_FLOOR` (initial ~0.5)
  and `GRAPH_TOP_K` (initial 8) start as constants; the implementation prints the
  actual pairwise-cosine distribution over the current 26 items and tunes them.
- **MVP only:** type coloring + click-to-detail + type filter + search highlight.
  No timeline, no cluster/community coloring, no typed edges (out of scope).

## Architecture

The contract files stay the source of truth; `atlas.db` stays a derived,
rebuildable view. Edges are part of that derived view — recomputed incrementally
on each `sync`, and fully on `sync --rebuild`. The page is server-rendered
(Jinja) and loads graph JSON from a read-only endpoint, matching the existing
`/api/search` pattern.

### New / changed modules

| Module | Responsibility |
|---|---|
| `aishelf/db/schema.py` | Add the `edges` table: `src TEXT NOT NULL, dst TEXT NOT NULL, weight REAL NOT NULL, PRIMARY KEY (src, dst)`. Edges are **undirected, stored canonically** with `src < dst` (string order) so each pair appears once. Reflected in `init_db`. Existing DBs pick it up via `init_db` (`CREATE TABLE IF NOT EXISTS`) — the table is empty until the next `sync`. |
| **`aishelf/db/graph.py`** (new) | Pure-ish graph logic over stored embeddings. `neighbors(target_vec, ids, matrix, *, floor) -> list[tuple[str, float]]` — cosine of one vector vs all others, keep pairs ≥ floor (excludes self). `recompute_edges_for(con, item_ids)` — for each changed id: delete its incident edges, recompute against all current embeddings, insert the ≥floor edges (canonical `src<dst`). `delete_edges_for(con, item_ids)` — drop edges incident to removed items. `rebuild_edges(con)` — clear + recompute all (used by `--rebuild`). `load_graph(db_path, *, cap_k) -> dict` — read nodes (`id,type,title,author` + computed `degree`) and edges, **capping each node to its top-K strongest edges**; returns `{"nodes": [...], "edges": [...]}`. |
| `aishelf/db/sync.py` | After embeddings are written: collect the ids whose embedding was (re)computed this run and call `graph.recompute_edges_for(con, those_ids)`; in the prune step call `graph.delete_edges_for(con, stale_ids)`. All within the existing single transaction. When embeddings are unavailable (no `ATLAS_EMBED_*`), no embeddings are written, so no edges are produced — the graph is simply empty (consistent with pure-FTS5 fallback). |
| `aishelf/db/__main__.py` | `--rebuild` already drops + recreates; ensure it ends with a full `graph.rebuild_edges` so a rebuilt DB has a complete edge set. |
| `aishelf/site/app.py` | `GET /graph` → render `graph.html` (page). `GET /api/graph` → JSON `{nodes:[{id,type,title,author,degree}], edges:[{source,target,weight}]}` from `graph.load_graph`. Read-only, ungated (like `/api/search`). |
| `aishelf/site/templates/graph.html` | Cytoscape.js page (CDN). Fetches `/api/graph`, lays out with `fcose`. Nodes colored by type (video vs blog), sized by degree, labeled by title (truncated); click → detail page (`/videos/{id}` or `/blogs/{id}`, new tab); hover → full title. A type filter (video/blog/all) and a search box that highlights/zooms matching nodes. Standalone-friendly but keeps the Atlas top nav (consistent with the rest of the site). Empty/low-data state: a friendly "先采集并嵌入更多内容" message. |
| `aishelf/site/templates/base.html` | Add a 「图谱」 link to the top nav. |

### Edge computation (the口径)

Storage layer — **threshold graph, symmetric, order-independent:**
- For items X and Y, an edge exists iff `cosine(X, Y) >= GRAPH_SIM_FLOOR`.
- Stored once, canonically (`src < dst`), `weight = cosine`.
- This is symmetric and independent of insertion order, so incremental updates
  stay consistent.

Read/display layer — **top-K cap per node:**
- `load_graph(cap_k)` keeps, for each node, only its `GRAPH_TOP_K` strongest
  incident edges (union across nodes — an edge survives if either endpoint keeps
  it). Prevents a dense "hairball" when many AI items are mutually similar.
- `degree` reported per node is computed after the cap (what the user sees).

Constants live in `graph.py`: `GRAPH_SIM_FLOOR` (initial 0.5), `GRAPH_TOP_K`
(initial 8). The implementation calibrates them by printing the pairwise-cosine
distribution over the real corpus before finalizing.

### Incremental update semantics

- **New / changed item:** `sync` (re)computes its embedding, then
  `recompute_edges_for([id])` deletes that id's incident edges and re-adds its
  current ≥floor edges against all embeddings. Because edges are symmetric and
  canonical, neighbors automatically gain/lose the edge — no neighbor needs a
  separate recompute.
- **Deleted item:** `delete_edges_for([id])` in the prune step removes its edges.
- **Full rebuild:** `sync --rebuild` → `rebuild_edges` recomputes everything.
- The user never rebuilds manually for normal use; opening `/graph` always
  reflects the latest `sync`.

## Data flow

1. Hermes writes content files → `sync` upserts rows, writes embeddings (when
   `ATLAS_EMBED_*` configured), then updates `edges` incrementally.
2. Browser opens `GET /graph` → page loads, fetches `GET /api/graph`.
3. `load_graph(cap_k=GRAPH_TOP_K)` reads nodes + top-K-capped edges → JSON.
4. Cytoscape renders the `fcose` layout; click a node → its detail page.

## Edge cases & resilience

- **No embeddings at all** (feature off / DB not yet embedded): `edges` is empty;
  `/api/graph` returns nodes with no edges, page shows the empty/low-data state.
- **Items without an embedding** (partial corpus): excluded from edge computation;
  they appear as isolated nodes (still clickable) so nothing silently vanishes.
- **Single item / empty library:** friendly empty state, no crash.
- **Malformed rows:** the loader/sync already skip+log; the graph only reads the
  `items` table, so it inherits that resilience.
- **Dimension mismatch after a model change:** `vector.load_embeddings(dim)`
  already filters by dim; edge recompute uses the current model's dim, so stale
  vectors are excluded until re-synced (same guard as `/ask`).

## Testing (network always mocked; live only under the `network` marker)

- **`db/graph.py` (pure):** `neighbors` returns ≥floor pairs sorted, excludes
  self; canonical `src<dst` storage; `load_graph` top-K cap keeps the strongest
  per node; symmetric/order-independent (inserting A-then-B vs B-then-A yields the
  same edge set).
- **`db/sync.py` (incremental):** inject fake embeddings — a new item produces
  edges to similar existing items; changing an item's vector updates its edges;
  deleting an item removes its edges; `rebuild` reproduces the full set; with no
  embedder configured, `edges` stays empty.
- **`/api/graph`:** JSON shape (`nodes`/`edges` keys + fields); top-K cap applied;
  empty DB → empty arrays, 200.
- **`/graph` page:** renders, contains the Cytoscape include and `/api/graph`;
  nav contains a 「图谱」 link.

## Out of scope (YAGNI)

- Concept/entity extraction (nodes are whole items, not sub-concepts).
- Typed/labeled edges ("builds on", "contradicts") or LLM-derived relationships.
- Timeline / temporal layout, community-detection coloring, edge bundling.
- On-the-fly (un-stored) computation, vector index / ANN — the stored threshold
  graph at this scale is fine; clustering/sub-graphs are a later concern if the
  corpus grows into the thousands.
- Curated/manual edges (the schema leaves room, but the UI/flows are not built).

## Risks & mitigations

- **Hairball in an all-AI corpus** (everything somewhat similar) → top-K display
  cap + calibrated floor; both are single constants to dial.
- **Threshold mis-set** → calibrate against the real 26-item distribution during
  implementation; `log` the chosen values.
- **Edge table drift vs files** → same as the rest of the derived DB; `sync` /
  `--rebuild` fixes it; documented.
- **Graph perf at scale** → fine for hundreds; flagged as a future concern with a
  clear escalation path (sub-graph / clustering), not built now.

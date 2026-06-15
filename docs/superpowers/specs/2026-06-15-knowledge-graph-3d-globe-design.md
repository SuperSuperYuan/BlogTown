# Knowledge Graph 3D Globe + Node Aliases

**Date:** 2026-06-15
**Status:** Design (approved, pre-plan)
**Scope:** Replace the 2D Cytoscape rendering on `/graph` with a 3D wireframe-sphere
("tech globe") visualization, and add LLM-generated short aliases for node labels.
Builds on the existing knowledge-graph feature (`edges` table, `db/graph.py`,
`/api/graph`) and the existing embeddings.

## Problem

The current `/graph` page (flat Cytoscape graph) is visually unappealing, and node
labels are full titles (long, noisy). The user wants a striking 3D wireframe globe
with nodes spread over the sphere surface, glowing connecting arcs, rotate/zoom, and
short readable node names (aliases).

We already have everything needed on the backend: per-item 1024-dim embeddings (for
meaningful node placement) and the `edges` table (for links). The two additions are
node **aliases** (short labels) and node **positions** (on the sphere).

## Decisions (locked)

- **Look:** wireframe "tech" sphere — dark space background, neon lat/lng wireframe
  globe, glowing node points colored by type (video/blog), glowing arc edges,
  slow auto-rotate + drag-rotate + scroll-zoom.
- **Library:** Three.js directly (WebGL) + OrbitControls (rotate/zoom) + CSS2DRenderer
  (labels), all via CDN. (Not Cytoscape, not globe.gl — a custom wireframe sphere fits
  the HUD look best.)
- **Node placement:** PCA the node embeddings to 3 dims, normalize each to the unit
  sphere → `(x, y, z)`. Semantically similar items cluster on the surface. Computed at
  **read time** in `load_graph` (not stored). Degrades to deterministic hash-based
  placement when there are <3 nodes or no embeddings.
- **Aliases:** DeepSeek (the configured `ATLAS_CHAT_*` model) generates a ≤8-character
  Chinese alias per item, stored in a new `items.alias` column, computed at **sync**
  time, regenerated only when the **title changes** (or alias missing) — note edits do
  not trigger regeneration. The globe shows the alias; hover/click shows the full title.
- **Degradation:** alias generation unconfigured/failed → alias stays NULL → frontend
  falls back to a truncated title. PCA unavailable → hash placement. Reads never crash.
- **Backward compatible:** `/api/graph` only *adds* node fields; edges unchanged.
- **Replace, don't add:** the 3D globe replaces the 2D rendering on the same `/graph`
  route. `/api/graph` stays the data source.

## Architecture

Files stay the source of truth; `atlas.db` stays the rebuildable derived view. The
`alias` column is part of that derived view (recomputed at sync, like embeddings/edges).
Node positions are a pure read-time projection of embeddings — not stored. The page is
server-rendered (Jinja, extends `base.html`) and loads graph JSON from `/api/graph`.

### New / changed modules

| Module | Responsibility |
|---|---|
| `aishelf/db/schema.py` | Add nullable `alias TEXT` column to `items`. |
| **`aishelf/alias.py`** (new, package root) | LLM alias client. Reads `ATLAS_CHAT_BASE_URL/_API_KEY/_MODEL` (falling back to the matching `HERMES_*`, mirroring `site/llm.py`); placed at the package root so `db` can use it without importing `site` (same pattern as `embed.py`). `is_configured() -> bool`; `generate_aliases(pairs: list[tuple[str,str]]) -> list[str] | None` — `pairs` is (title, summary); batched (~20/request) into one chat call per batch that returns a JSON array of ≤8-char aliases; validates the array length per batch; returns `None` if unconfigured, empty input, or on any error/parse failure (all-or-nothing, like `embed.embed_texts`). Each alias is cleaned (strip quotes/whitespace) and hard-capped to 10 chars as a safety net. |
| `aishelf/db/sync.py` | After embeddings, generate aliases for items whose **title changed or alias is NULL**. The `existing` map gains `title` and `alias`-presence so the decision needs no extra hash. Gather `(title, summary)` for those ids, call `alias.generate_aliases`, `UPDATE items SET alias=?`. On `None`, leave alias NULL (no crash). Same transaction as the rest of sync. |
| `aishelf/db/graph.py` | `load_graph` enriches each node with `alias` (from the column) and `x,y,z` (unit-sphere position). New `_sphere_positions(ids, groups) -> dict[str, tuple]`: PCA the embedding matrix (centered SVD, top-3 components), project, L2-normalize each row to the unit sphere; ids without an embedding (or when <3 embedded nodes / degenerate PCA) get a deterministic hash-based unit-sphere point so every node always has a position. |
| `aishelf/site/app.py` | No route change — `/api/graph` already calls `load_graph`; it now returns the enriched nodes. |
| `aishelf/site/templates/graph.html` | Replace the Cytoscape implementation with a Three.js wireframe globe (details below). Still extends `base.html`. |
| `CLAUDE.md`, `docs/ARCHITECTURE.md` | Document the alias column/module, the 3D globe, and the read-time PCA placement. |

### `/api/graph` shape (after)

```json
{
  "nodes": [{"id","type","title","alias","degree","x","y","z"}],
  "edges": [{"source","target","weight"}]
}
```

`x,y,z` are unit-sphere coordinates (‖(x,y,z)‖ ≈ 1). `alias` may be `""`/null (frontend
falls back to a truncated title). `edges` are unchanged (top-K-capped, orphan-filtered).

### Frontend `graph.html` (Three.js)

- CDN: Three.js (pinned), `OrbitControls`, `CSS2DRenderer` (+ `CSS2DObject`).
- **Scene:** dark background; a neon **wireframe sphere** (lat/lng grid) at radius `R`;
  subtle starfield/points optional; ambient + point light for the glow.
- **Nodes:** small emissive spheres (or sprite points) placed at `(x,y,z)·R`, colored
  by type (video vs blog), radius scaled by `degree`. Each carries a CSS2D label = alias
  (or truncated title if no alias).
- **Edges:** for each edge, a glowing quadratic-bezier arc bulging slightly outside the
  sphere between the two node positions; width/opacity by `weight`.
- **Controls:** OrbitControls (drag-rotate, scroll-zoom), slow `autoRotate`.
- **Interaction:** raycaster — hover highlights a node + shows a tooltip with the full
  title; click opens the detail page (`/videos/{id}` or `/blogs/{id}`, new tab). A type
  filter (all/video/blog) and a search box that highlights matching nodes (dims the
  rest) — same affordances as the current page.
- **Empty state:** when `/api/graph` returns no nodes, show the existing "先采集并嵌入"
  guidance and skip the scene.

## Data flow

1. `sync`: write embeddings → generate+store aliases for changed-title/new items →
   update edges.
2. Browser opens `/graph` → fetches `/api/graph` → `load_graph` returns nodes (with
   alias + PCA `x,y,z`) and edges.
3. Three.js renders the wireframe globe; nodes at their sphere coords, arcs for edges;
   rotate/zoom; click a node → detail page.

## Edge cases & resilience

- **Aliases off / LLM error:** alias NULL → frontend truncates the title. No crash.
- **Note edit:** title unchanged → alias not regenerated (no wasted LLM call).
- **<3 nodes / no embeddings:** PCA skipped → deterministic hash placement; globe still
  renders (nodes spread, just not semantically clustered).
- **Node without embedding:** hash placement for that node; still clickable.
- **Empty graph:** empty state, no WebGL init.
- **`alias` column missing on an old DB:** `init_db` adds it (CREATE TABLE only affects
  fresh tables) — existing deployments run the one-time `sync --rebuild` (already
  required for edges) which also backfills aliases.

## Testing (network always mocked; live only under the `network` marker)

- **`alias.py`:** monkeypatch the client — batched request shape; JSON-array parse →
  list; unconfigured → None; empty input → None; malformed/short response → None;
  alias cleaned + length-capped.
- **`db/sync.py`:** inject a fake alias generator — new item gets an alias stored;
  title change regenerates; note-only change does **not** regenerate; unconfigured →
  alias stays NULL; all within the existing sync tests' style.
- **`db/graph.py`:** `load_graph` nodes include `alias` and `x,y,z` with ‖·‖≈1; the
  hash-placement fallback triggers for <3 embedded nodes and for an embedding-less node;
  positions are deterministic for a fixed input.
- **`/api/graph`:** node objects contain the new fields; shape stays `{nodes,edges}`.
- **`/graph` page:** renders; contains the Three.js include, `/api/graph`, and the
  alias-fallback path (e.g. references both `alias` and a truncation).

## Out of scope (YAGNI)

- Storing node positions (recomputed at read time by design).
- Real-Earth texture / geographic placement (chosen look is an abstract wireframe).
- LLM-regenerating aliases on summary-only changes (gated on title only).
- Batched-per-item alias parsing beyond a JSON array; clustering/community coloring;
  VR/AR; server-side 3D.
- Editing/curating aliases in the UI (the column exists; no UI).

## Risks & mitigations

- **PCA cost at scale:** SVD of N×1024 each `/graph` load — fine for hundreds–low
  thousands; if the corpus grows large, cache/precompute (noted, not built).
- **Label clutter on the globe:** aliases are ≤8 chars; if still busy, show labels only
  for hovered + high-degree nodes (tunable in the frontend).
- **Alias quality/LLM cost:** one batched call per sync over changed-title items; rare
  after initial backfill. Truncation fallback guarantees a usable label regardless.
- **Three.js CDN offline:** `/graph` needs network for the CDN libs (consistent with
  the existing Cytoscape/Google-Fonts CDN choices); flagged, not blocking.

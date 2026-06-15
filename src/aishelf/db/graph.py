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

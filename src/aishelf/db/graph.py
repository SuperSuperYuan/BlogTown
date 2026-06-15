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

"""Idea-collision pair selection + prompt building (mostly pure).

Mirrors graph.py's split: pure selection logic (pick_pair / random_pair /
build_messages) plus one thin DB loader (load_pair_space). Picks a "surprising"
pair — embedding cosine in a mid band [0.30, GRAPH_SIM_FLOOR), preferring
cross-type and cross-author — for the LLM to synthesize. Reuses ATLAS_CHAT_* via
the site llm client and ATLAS_EMBED_* via stored embeddings; no new config.
"""

from __future__ import annotations

import numpy as np

from aishelf.db import graph

BAND_LO = 0.30
BAND_HI = graph.GRAPH_SIM_FLOOR  # 0.50 — at/above this the graph already draws an edge


def _cosine_matrix(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normed = matrix / (norms + 1e-12)
    return normed @ normed.T


def pick_pair(ids, matrix, meta, *, lock_id=None, rng, lo=BAND_LO, hi=BAND_HI):
    """A surprising (id_a, id_b) pair: cosine in [lo, hi), preferring cross-type
    and cross-author, chosen at random (via rng) from the best-scoring tier.
    With lock_id, restrict to pairs containing it and return it first. None when
    there are fewer than 2 items or no in-band candidates (caller falls back)."""
    n = len(ids)
    if n < 2:
        return None
    sims = _cosine_matrix(np.asarray(matrix, dtype=np.float32))
    cands = []  # (score, a, b)
    for i in range(n):
        for j in range(i + 1, n):
            s = float(sims[i, j])
            if not (lo <= s < hi):
                continue
            a, b = ids[i], ids[j]
            if lock_id is not None and lock_id not in (a, b):
                continue
            ma, mb = meta.get(a, {}), meta.get(b, {})
            score = int(ma.get("type") != mb.get("type")) + int(ma.get("author") != mb.get("author"))
            cands.append((score, a, b))
    if not cands:
        return None
    best = max(c[0] for c in cands)
    top = sorted((c for c in cands if c[0] == best), key=lambda c: (c[1], c[2]))
    _, a, b = rng.choice(top)
    if lock_id is not None and b == lock_id:
        a, b = b, a
    return (a, b)


def random_pair(item_ids, *, lock_id=None, rng):
    """Fallback: two distinct ids at random (honoring lock_id). None when <2."""
    ids = list(item_ids)
    if len(ids) < 2:
        return None
    if lock_id is not None and lock_id in ids:
        others = [i for i in ids if i != lock_id]
        return (lock_id, rng.choice(others))
    return tuple(rng.sample(ids, 2))

"""Semantic clustering over stored embeddings (主题星系).

Pure helpers (choose_k / kmeans / representatives / color_for) plus one thin DB
writer (recompute_clusters), mirroring the graph.py / collide.py split. numpy
k-means on L2-normalized vectors (cosine clustering); no sklearn. Clusters are a
rebuildable derived view written at sync time.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from aishelf.db import graph

CLUSTER_SEED = 1234

# Fixed palette; cluster colour is PALETTE[id % len] so re-syncs stay stable.
PALETTE = [
    "#ff9a3c", "#4cc2ff", "#38e1c0", "#c08cff",
    "#ff6b9d", "#ffd166", "#7ee787", "#8ab4ff",
]


def choose_k(n: int) -> int:
    """How many galaxies for n embedded items: clamp(round(sqrt(n/3)), 3, 8),
    degrading to a single cluster below 3 items."""
    if n < 3:
        return 1
    return max(3, min(8, round(math.sqrt(n / 3))))


def color_for(cluster_id: int) -> str:
    return PALETTE[cluster_id % len(PALETTE)]


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / (norms + 1e-12)


def kmeans(matrix, k: int, *, seed: int, iters: int = 50):
    """Lloyd's k-means on L2-normalized rows (== cosine clustering). Deterministic
    for a given seed. Returns one int label per row. k is clamped to [1, n]."""
    mat = np.asarray(matrix, dtype=np.float32)
    n = mat.shape[0]
    if n == 0:
        return np.empty((0,), dtype=int)
    k = max(1, min(k, n))
    if k == 1:
        return np.zeros(n, dtype=int)
    x = _normalize(mat)
    rng = np.random.default_rng(seed)
    centroids = x[rng.choice(n, size=k, replace=False)].copy()
    labels = np.full(n, -1, dtype=int)
    for _ in range(iters):
        new_labels = np.argmax(x @ centroids.T, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for c in range(k):
            members = x[labels == c]
            if len(members):
                v = members.mean(axis=0)
                nv = float(np.linalg.norm(v))
                centroids[c] = v / nv if nv > 1e-12 else x[rng.integers(n)]
            else:
                centroids[c] = x[rng.integers(n)]
    return labels


def representatives(labels, matrix, ids, *, m: int = 6) -> dict[int, list[str]]:
    """{cluster_id: [ids]} — up to m ids per cluster, nearest the cluster centroid
    first (cosine on L2-normalized vectors)."""
    x = _normalize(np.asarray(matrix, dtype=np.float32))
    labels = np.asarray(labels)
    out: dict[int, list[str]] = {}
    for c in sorted({int(v) for v in labels}):
        idx = np.where(labels == c)[0]
        members = x[idx]
        centroid = members.mean(axis=0)
        nc = float(np.linalg.norm(centroid))
        if nc > 1e-12:
            centroid = centroid / nc
        order = idx[np.argsort(-(members @ centroid))][:m]
        out[c] = [ids[i] for i in order]
    return out


def _signature(ids: list[str]) -> str:
    return hashlib.sha1("\x00".join(sorted(ids)).encode("utf-8")).hexdigest()


def recompute_clusters(con, *, seed: int = CLUSTER_SEED) -> dict[int, list[str]]:
    """Recompute global clusters from stored embeddings; rewrite items.cluster and
    the clusters table. A cluster's name is carried over when its exact member set
    (signature) is unchanged, so only genuinely new/changed clusters need (LLM)
    naming. Returns {cluster_id: [representative titles]} for clusters that still
    need a name — empty when there are no embeddings."""
    groups = graph._load_groups(con)
    prev_names = {
        r["signature"]: r["name"]
        for r in con.execute("SELECT signature, name FROM clusters")
        if r["signature"] and r["name"]
    }
    con.execute("UPDATE items SET cluster = NULL")
    con.execute("DELETE FROM clusters")
    if not groups:
        return {}
    dim = max(groups, key=lambda d: len(groups[d][0]))
    ids, mat = groups[dim]
    labels = kmeans(mat, choose_k(len(ids)), seed=seed)
    reps = representatives(labels, mat, ids)

    members: dict[int, list[str]] = {}
    for sid, lab in zip(ids, labels):
        con.execute("UPDATE items SET cluster = ? WHERE id = ?", (int(lab), sid))
        members.setdefault(int(lab), []).append(sid)

    title_of = {r["id"]: r["title"]
                for r in con.execute("SELECT id, title FROM items WHERE cluster IS NOT NULL")}
    need: dict[int, list[str]] = {}
    for cid in sorted(members):
        sig = _signature(members[cid])
        name = prev_names.get(sig)
        con.execute(
            "INSERT INTO clusters (id, name, color, signature) VALUES (?,?,?,?)",
            (cid, name, color_for(cid), sig),
        )
        if not name:
            need[cid] = [title_of[i] for i in reps.get(cid, []) if i in title_of]
    return need

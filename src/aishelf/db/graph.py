"""Semantic knowledge graph over the content library.

Nodes are content items; edges are embedding cosine similarity. Storage keeps
the full threshold graph (every pair with cosine >= GRAPH_SIM_FLOOR, stored once
canonically with src < dst). The read side (load_graph) caps each node to its
top-K strongest edges so a dense, all-AI corpus does not render as a hairball.
Edges are recomputed incrementally at sync time.
"""

from __future__ import annotations

import hashlib

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
                norms = np.linalg.norm(coords, axis=1)
                for sid, row, nrm in zip(ids, coords, norms):
                    if nrm > 1e-9:   # zero-norm row (degenerate) -> hash fallback below
                        pos[sid] = (float(row[0] / nrm), float(row[1] / nrm), float(row[2] / nrm))
            except np.linalg.LinAlgError:
                pass
    for sid in node_ids:
        if sid not in pos:
            pos[sid] = _hash_point(sid)
    return pos


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


def load_graph(db_path, *, cap_k: int = GRAPH_TOP_K) -> dict:
    """Nodes (id/type/title/alias/degree + unit-sphere x,y,z) and edges, capping each node to its top-K strongest incident edges (an edge survives if it is in the top-K of either endpoint). Degree counts the kept edges."""
    con = schema.connect(db_path)
    try:
        schema.init_db(con)
        node_rows = con.execute(
            "SELECT id, type, title, alias, cluster, collected_at, hook FROM items"
        ).fetchall()
        edge_rows = con.execute("SELECT src, dst, weight FROM edges").fetchall()
        cluster_rows = con.execute("SELECT id, name, color FROM clusters").fetchall()
        groups = _load_groups(con)
    finally:
        con.close()

    # Drop any edge whose endpoint has no item row (defensive: a malformed/stale
    # edge would otherwise make the frontend graph library throw on a missing node).
    node_ids = {r["id"] for r in node_rows}
    edge_rows = [r for r in edge_rows if r["src"] in node_ids and r["dst"] in node_ids]

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

    csize: dict[int, int] = {}
    for r in node_rows:
        if r["cluster"] is not None:
            csize[r["cluster"]] = csize.get(r["cluster"], 0) + 1
    clusters = [
        {"id": r["id"], "name": r["name"] or "", "color": r["color"] or "",
         "size": csize.get(r["id"], 0)}
        for r in cluster_rows
    ]

    positions = _sphere_positions([r["id"] for r in node_rows], groups)
    nodes = []
    for r in node_rows:
        x, y, z = positions[r["id"]]
        nodes.append({
            "id": r["id"], "type": r["type"], "title": r["title"],
            "alias": r["alias"] or "", "degree": degree.get(r["id"], 0),
            "cluster": r["cluster"], "collected_at": r["collected_at"],
            "hook": r["hook"] or "",
            "x": x, "y": y, "z": z,
        })
    return {"nodes": nodes, "edges": edges, "clusters": clusters}


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

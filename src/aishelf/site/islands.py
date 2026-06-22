"""语义孤岛/孤本 (Islands) builder + loader, mirroring timeline.py.

Pure `build_islands` ranks embedded items by their degree in the semantic
`edges` graph — 孤本 (degree 0) and 弱连接 (1..WEAK_MAX_DEGREE neighbors) — to
surface the most isolated collections; tolerant `load_islands` reads the
derived items/edges tables and feeds the builder. No LLM, no persistence —
pure per-request assembly.
"""

from __future__ import annotations

import sqlite3

from aishelf.db import schema

WEAK_MAX_DEGREE = 2


def build_islands(items, edges, *, max_weak_degree: int = WEAK_MAX_DEGREE) -> dict:
    """Split embedded items into 孤本 (degree 0) / 弱连接 (1..max) / connected. Pure."""
    by_id = {it["id"]: it for it in items}
    neighbors: dict = {it["id"]: set() for it in items}
    for src, dst in edges:
        if src != dst and src in by_id and dst in by_id:
            neighbors[src].add(dst)
            neighbors[dst].add(src)

    def _entry(it):
        return {"id": it["id"], "type": it.get("type"),
                "title": it.get("title"), "hook": it.get("hook") or ""}

    lone, weak = [], []
    for it in items:
        deg = len(neighbors[it["id"]])
        if deg == 0:
            lone.append(_entry(it))
        elif deg <= max_weak_degree:
            e = _entry(it)
            nbrs = []
            for nid in neighbors[it["id"]]:
                n = by_id.get(nid)
                if n is not None:
                    nbrs.append({"id": n["id"], "type": n.get("type"), "title": n.get("title")})
            nbrs.sort(key=lambda n: ((n["title"] or ""), n["id"]))
            e["degree"] = deg
            e["neighbors"] = nbrs
            weak.append(e)

    lone.sort(key=lambda e: ((e["title"] or ""), e["id"]))
    weak.sort(key=lambda e: (e["degree"], (e["title"] or ""), e["id"]))

    connected = len(items) - len(lone) - len(weak)
    return {
        "lone": lone,
        "weak": weak,
        "stats": {"embedded": len(items), "lone": len(lone),
                  "weak": len(weak), "connected": connected},
    }


def load_islands(db_path) -> dict:
    """Read embedded items + edges from the derived DB and build the islands view.

    Tolerant of a missing/old/broken DB: returns an empty result, never raises
    (mirrors timeline.load_timeline)."""
    try:
        con = schema.connect(db_path)
        try:
            schema.init_db(con)
            rows = con.execute(
                "SELECT id, type, title, hook FROM items WHERE embedding IS NOT NULL"
            ).fetchall()
            edge_rows = con.execute("SELECT src, dst FROM edges").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return build_islands([], [])
    items = [{"id": r["id"], "type": r["type"], "title": r["title"], "hook": r["hook"]}
             for r in rows]
    edges = [(r["src"], r["dst"]) for r in edge_rows]
    return build_islands(items, edges)

"""收藏编年史 (Timeline) builder + loader, mirroring digest.py / learn.py.

Pure `build_timeline` groups items into month buckets (reverse-chronological)
with per-item galaxy color/hook, plus a stats header and color legend; tolerant
`load_timeline` reads the derived items/clusters tables and feeds the builder.
No LLM, no caching, no persistence — pure per-request assembly.
"""

from __future__ import annotations

import sqlite3

from aishelf.db import schema

UNCLASSIFIED_COLOR = "#888888"
_UNCLASSIFIED_NAME = "未归类"


def _month_key(collected_at) -> str:
    """`YYYY-MM` prefix of an ISO timestamp, or "" when too short/missing."""
    s = collected_at or ""
    return s[:7] if len(s) >= 7 and s[4] == "-" else ""


def _month_title(key: str) -> str:
    if not key:
        return "未知时间"
    return f"{int(key[:4])}年{int(key[5:7])}月"


def build_timeline(items: list, clusters_by_id: dict) -> dict:
    """Month-grouped reverse-chronological timeline + stats + legend. Pure."""
    # Reverse-chronological; ISO strings sort lexicographically. Empty/malformed
    # collected_at ("") sorts last under reverse. Tie-break by id for determinism.
    ordered = sorted(items, key=lambda it: ((it.get("collected_at") or ""), it.get("id") or ""),
                     reverse=True)

    months: list = []
    by_key: dict = {}
    galaxy_counts: dict = {}   # name -> [count, color]
    keys_seen: list = []

    for it in ordered:
        cid = it.get("cluster")
        cluster = clusters_by_id.get(cid) if cid is not None else None
        if cluster and cluster.get("name"):
            name, color = cluster["name"], (cluster.get("color") or UNCLASSIFIED_COLOR)
        else:
            name, color = _UNCLASSIFIED_NAME, UNCLASSIFIED_COLOR

        entry = {
            "id": it.get("id"),
            "type": it.get("type"),
            "title": it.get("title"),
            "hook": it.get("hook") or "",
            "cluster_name": name,
            "cluster_color": color,
        }

        key = _month_key(it.get("collected_at"))
        if key not in by_key:
            bucket = {"title": _month_title(key), "count": 0, "items": []}
            by_key[key] = bucket
            months.append(bucket)
            if key:
                keys_seen.append(key)
        by_key[key]["items"].append(entry)
        by_key[key]["count"] += 1

        gc = galaxy_counts.setdefault(name, [0, color])
        gc[0] += 1

    # span
    if keys_seen:
        lo, hi = min(keys_seen), max(keys_seen)
        span = _month_title(hi) if lo == hi else f"{_month_title(lo)} – {_month_title(hi)}"
    else:
        span = ""

    # top galaxy (exclude 未归类; tie -> name asc)
    classified = [(n, c[0], c[1]) for n, c in galaxy_counts.items() if n != _UNCLASSIFIED_NAME]
    if classified:
        classified.sort(key=lambda t: (-t[1], t[0]))
        n, cnt, col = classified[0]
        top_galaxy = {"name": n, "color": col, "count": cnt}
    else:
        top_galaxy = None

    # legend: count desc, 未归类 last
    legend_items = sorted(
        galaxy_counts.items(),
        key=lambda kv: (kv[0] == _UNCLASSIFIED_NAME, -kv[1][0], kv[0]),
    )
    legend = [{"name": n, "color": c[1]} for n, c in legend_items]

    return {
        "months": months,
        "stats": {"total": len(items), "span": span, "top_galaxy": top_galaxy},
        "legend": legend,
    }


def load_timeline(db_path) -> dict:
    """Read items + clusters from the derived DB and build the timeline.

    Tolerant of a missing/old/broken DB: returns an empty timeline, never
    raises (mirrors learn.load_galaxies)."""
    try:
        con = schema.connect(db_path)
        try:
            schema.init_db(con)
            clusters = {
                r["id"]: {"name": r["name"] or "", "color": r["color"] or ""}
                for r in con.execute("SELECT id, name, color FROM clusters")
            }
            rows = con.execute(
                "SELECT id, type, title, collected_at, cluster, hook FROM items"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return build_timeline([], {})
    items = [
        {"id": r["id"], "type": r["type"], "title": r["title"],
         "collected_at": r["collected_at"], "cluster": r["cluster"], "hook": r["hook"]}
        for r in rows
    ]
    return build_timeline(items, clusters)

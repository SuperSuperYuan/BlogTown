"""Learning-path (进阶路线) loader + prompt builder, mirroring collide.py / mirror.py.

Pure `build_messages` (sequences a theme galaxy's items into an ordered 中文
curriculum) + one tolerant DB loader `load_galaxies` (reads the clusters/items
derived tables). The route does the streaming; this module only reads + phrases.
Reuses ATLAS_CHAT_* via the site llm client; no new config, no persistence.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from aishelf.db import schema


@dataclass
class Item:
    id: str
    title: str
    summary: str
    type: str       # "video" | "blog"


@dataclass
class Galaxy:
    id: int
    name: str       # cluster name; "" when unnamed
    color: str      # clusters.color
    size: int
    items: list = field(default_factory=list)   # list[Item]


def _fmt_item(i: int, it: dict) -> str:
    summary = (it.get("summary") or "")[:80]
    return f"{i}. {it.get('title', '')}（{it.get('type', '')}）— {summary}"


def build_messages(galaxy_name: str, items: list[dict]) -> list[dict]:
    """System + user messages asking for an ordered learning path over a galaxy's
    items. `items` are dicts with id/title/summary/type. Pure — no DB, no LLM."""
    system = (
        '你是一个课程设计者。用户会给你某个主题星系里收藏的若干内容（标题+摘要）。'
        '请把它们排成一条由浅入深的学习路线：入门 → 进阶 → 纵深。先用一句话概述这条线'
        '整体怎么走，然后逐条列出顺序，每条另起一行：以该内容的【完整标题原文】开头，'
        '再接“ — ”和不超过一句话的理由（为什么排在这一步）。只能用我给你的这些内容，'
        '不要杜撰别的；如果只有一条，就直说这条目前是孤本。'
        '输出纯文本，不要使用 Markdown 语法（不要 # 或 * 等），不要额外开场白或总结。'
    )
    listing = "\n".join(_fmt_item(i + 1, it) for i, it in enumerate(items))
    user = f"主题星系：{galaxy_name}\n这个星系里的内容：\n{listing}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def load_galaxies(db_path) -> list:
    """All theme galaxies (each with its items), sorted by size desc. Returns []
    when there are no clustered items / the DB is missing. Tolerant of a
    missing/old DB (returns [], never raises) — like mirror.load_profile."""
    try:
        con = schema.connect(db_path)
        try:
            schema.init_db(con)
            clusters = {
                r["id"]: (r["name"] or "", r["color"] or "")
                for r in con.execute("SELECT id, name, color FROM clusters")
            }
            rows = con.execute(
                "SELECT id, type, title, summary, cluster "
                "FROM items WHERE cluster IS NOT NULL"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    by_cluster: dict[int, list] = {}
    for r in rows:
        by_cluster.setdefault(r["cluster"], []).append(r)
    galaxies = []
    for cid, members in by_cluster.items():
        name, color = clusters.get(cid, ("", ""))
        items = [Item(id=m["id"], title=m["title"], summary=m["summary"], type=m["type"])
                 for m in members]
        galaxies.append(Galaxy(id=cid, name=name, color=color, size=len(items), items=items))
    galaxies.sort(key=lambda g: (-g.size, g.name))
    return galaxies

"""Collection-persona mirror (藏书镜): synthesize the whole collection's theme
galaxies into a 中文 reading-persona portrait.

Mirrors collide.py / path.py: one tolerant DB loader (load_profile) + one pure
prompt builder (build_messages). Reuses ATLAS_CHAT_* via the site llm client and
the clusters/items tables already built at sync time. On-demand, no persistence,
no new config.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from aishelf.db import schema


@dataclass
class Galaxy:
    name: str          # cluster name; "" when unnamed (alias pipeline off)
    color: str         # clusters.color — fact-strip pill colour (matches /graph)
    size: int          # member count
    recent: int        # members within the recent-N window (for 转向)
    titles: list[str]  # up to 5 sample member titles (grounding for the LLM)


@dataclass
class Profile:
    galaxies: list           # list[Galaxy], sorted by size desc
    total: int               # items with a cluster
    videos: int
    blogs: int
    top_authors: list        # list[tuple[str, int]], up to 3, blanks skipped
    span_days: int           # earliest→latest collected_at, 0 if unknown
    recent_n: int


def _fmt_galaxy(g: "Galaxy") -> str:
    name = g.name or "（未命名星系）"
    titles = "；".join(g.titles)
    return f"- {name}（{g.size} 条，最近 {g.recent} 条）：{titles}"


def build_messages(profile: "Profile") -> list[dict]:
    """System + user chat messages asking for the bracketed 中文 portrait.

    Pure — no DB, no LLM. `profile` is a Profile built by load_profile."""
    system = (
        "你是一面懂行又毒舌的镜子。用户会给你一份他收藏内容的画像数据——若干"
        "主题星系（每个有规模、最近活跃度、代表标题）以及整体统计。请据此读出这个"
        "人的阅读人格。输出恰好四段，每段以方括号小标题开头，再加结尾一句建议，"
        "具体、有锋芒、不要空话套话：\n"
        "【你的主线】挑 2-3 个最大的星系，每条 1-2 句，点破他在痴迷什么。\n"
        "【最近的转向】最近收藏相对整体偏向了什么；若无明显转向就直说没有。1-2 句。\n"
        "【一个盲区】最薄的那个星系，1-2 句，略带锋芒。\n"
        "【一句话人格】一句俏皮的人格速写。\n"
        "最后另起一行，给一句具体的下一步建议——只能从他已有的收藏延伸（补一补某个"
        "盲区，或顺着某条主线深挖），不要推荐站外的东西。\n"
        "只输出这些纯文本，不要使用 Markdown 语法（不要 # 或 * 等），"
        "不要额外的开场白或总结。"
    )
    gx = "\n".join(_fmt_galaxy(g) for g in profile.galaxies)
    authors = "、".join(f"{a}（{c}）" for a, c in profile.top_authors) or "（不详）"
    user = (
        f"主题星系（按规模从大到小）：\n{gx}\n\n"
        f"整体：共 {profile.total} 条（{profile.videos} 视频 / {profile.blogs} 博客），"
        f"收藏时间跨度约 {profile.span_days} 天，最近窗口取最新 {profile.recent_n} 条。\n"
        f"高频作者：{authors}。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _collected_key(raw: str):
    """ISO collected_at -> naive-UTC datetime; unparseable sorts last.

    Same tolerant logic as digest._collected_key (kept local so mirror stays a
    leaf module — no cross-import)."""
    try:
        dt = datetime.fromisoformat(raw or "")
    except ValueError:
        return datetime.min
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def load_profile(db_path, *, recent_n: int = 10):
    """Build a Profile from the derived DB, or None when there are no clustered
    items / no DB. Tolerant of a missing/old DB (returns None, never raises) —
    same posture as db.search.hooks_for / collide.load_pair_space."""
    try:
        con = schema.connect(db_path)
        try:
            schema.init_db(con)
            clusters = {
                r["id"]: (r["name"] or "", r["color"] or "")
                for r in con.execute("SELECT id, name, color FROM clusters")
            }
            rows = con.execute(
                "SELECT id, type, author, collected_at, title, cluster "
                "FROM items WHERE cluster IS NOT NULL"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not rows:
        return None

    ordered = sorted(
        rows, key=lambda r: (_collected_key(r["collected_at"] or ""), r["id"]),
        reverse=True,
    )
    recent_ids = {r["id"] for r in ordered[:recent_n]}

    by_cluster: dict[int, list] = {}
    for r in rows:
        by_cluster.setdefault(r["cluster"], []).append(r)

    galaxies = []
    for cid, members in by_cluster.items():
        name, color = clusters.get(cid, ("", ""))
        recent = sum(1 for m in members if m["id"] in recent_ids)
        titles = [m["title"] for m in members[:5]]
        galaxies.append(Galaxy(name=name, color=color, size=len(members),
                               recent=recent, titles=titles))
    galaxies.sort(key=lambda g: (-g.size, g.name))

    videos = sum(1 for r in rows if r["type"] == "video")
    blogs = sum(1 for r in rows if r["type"] == "blog")

    author_counts: dict[str, int] = {}
    for r in rows:
        a = (r["author"] or "").strip()
        if a:
            author_counts[a] = author_counts.get(a, 0) + 1
    top_authors = sorted(author_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]

    dts = [_collected_key(r["collected_at"] or "") for r in rows]
    dts = [d for d in dts if d != datetime.min]
    span_days = (max(dts) - min(dts)).days if len(dts) >= 2 else 0

    return Profile(galaxies=galaxies, total=len(rows), videos=videos, blogs=blogs,
                   top_authors=top_authors, span_days=span_days, recent_n=recent_n)

"""Idea-collision pair selection + prompt building (mostly pure).

Mirrors graph.py's split: pure selection logic (pick_pair / random_pair /
build_messages) plus one thin DB loader (load_pair_space). Picks a "surprising"
pair — embedding cosine in a mid band [0.30, GRAPH_SIM_FLOOR), preferring
cross-type and cross-author — for the LLM to synthesize. Reuses ATLAS_CHAT_* via
the site llm client and ATLAS_EMBED_* via stored embeddings; no new config.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from aishelf.db import graph, schema, vector

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


def load_pair_space(db_path):
    """(ids, matrix, meta) for the largest same-dimension embedding group.

    meta[id] = {"type", "author"}. Returns empties when there are no embeddings
    or the DB is missing/old (so the caller can fall back to a random pair).
    """
    empty = ([], np.empty((0, 0), dtype=np.float32), {})
    try:
        con = schema.connect(db_path)
        try:
            schema.init_db(con)
            rows = con.execute(
                "SELECT id, embedding, embedding_dim, type, author FROM items "
                "WHERE embedding IS NOT NULL"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return empty
    by_dim: dict[int, list] = {}
    for r in rows:
        by_dim.setdefault(r["embedding_dim"], []).append(r)
    if not by_dim:
        return empty
    dim = max(by_dim, key=lambda d: len(by_dim[d]))
    group = by_dim[dim]
    ids = [r["id"] for r in group]
    matrix = np.stack([vector.unpack(r["embedding"]) for r in group])
    meta = {r["id"]: {"type": r["type"], "author": r["author"]} for r in group}
    return ids, matrix, meta


def _fmt_item(x) -> str:
    kw = "、".join(x.get("keywords") or [])
    lines = [f"标题：{x['title']}", f"作者：{x.get('author', '')}", f"摘要：{x.get('summary', '')}"]
    if kw:
        lines.append(f"关键词：{kw}")
    return "\n".join(lines)


def build_messages(a, b) -> list[dict]:
    """System + user messages asking for exactly three plain-text sections.
    `a`/`b` are dicts with title/summary/keywords/author/type."""
    system = (
        "你是一个善于发现跨领域联系的思考者。用户会给你两条 AI 领域的内容，"
        "请把它们放在一起碰撞，输出恰好三段，每段以方括号小标题开头，每段 1-2 句，"
        "具体、有锋芒、不要空话套话：\n"
        "【共同的暗线】它们没明说但共享的线索。\n"
        "【关键张力】它们相互拉扯或分歧之处。\n"
        "【碰撞出的新点子】把两者结合后迸发的一个新想法。\n"
        "只输出这三段纯文本，不要使用 Markdown 语法（不要 # 或 * 等），"
        "不要额外的开场白或总结。"
    )
    user = (
        f"内容 A（{a.get('type', '')}）：\n{_fmt_item(a)}\n\n"
        f"内容 B（{b.get('type', '')}）：\n{_fmt_item(b)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

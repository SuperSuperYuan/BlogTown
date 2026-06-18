"""Semantic-path explanation prompt (pure), mirroring collide.py's pure half.

Given the ordered items on a path between two nodes, build the chat messages
that ask the model to explain the conceptual bridge from start to end. The
route is found client-side over the graph edges; this module only phrases the
explanation. Streamed by POST /graph/path via llm.stream_completion.
"""

from __future__ import annotations


def _fmt(i: int, x: dict, n: int) -> str:
    role = "起点" if i == 0 else ("终点" if i == n - 1 else f"第{i}步")
    return f"{role}：{x['title']}（{x.get('type', '')}）— {(x.get('summary') or '')[:80]}"


def build_messages(items: list[dict]) -> list[dict]:
    """System + user messages for explaining a semantic path. `items` are dicts
    with title/summary/author/type, in path order (start → end)."""
    system = (
        "你是一个善于把想法串起来的思考者。用户会给你一条知识路径——从起点内容出发，"
        "经过若干跳，到达终点内容。请解释这条路径如何把起点和终点连起来：每一跳为什么"
        "顺理成章，整条路又揭示了什么共同的暗线。输出恰好两段纯文本：\n"
        "【这条路怎么走通的】顺着路径把相邻两步的关联讲清楚，1-3 句。\n"
        "【它们共享的暗线】这条路背后没明说的那条主线，1-2 句。\n"
        "具体、有锋芒、不要空话套话。只输出这两段纯文本，不要使用 Markdown 语法"
        "（不要 # 或 * 等），不要额外开场白或总结。"
    )
    n = len(items)
    steps = "\n".join(_fmt(i, x, n) for i, x in enumerate(items))
    user = f"路径上的内容依次是：\n{steps}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

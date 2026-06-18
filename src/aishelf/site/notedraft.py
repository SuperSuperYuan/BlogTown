"""AI note-draft prompt builder (pure), mirroring collide.py / path.py / mirror.py.

Given an item's metadata (and any existing note), build the chat messages that
ask the model to draft a short Markdown note *skeleton* — 要点 / 为什么值得记 /
待探索 — for the user to edit and save. The route does the item lookup and
streaming; this module only phrases the prompt. Reuses ATLAS_CHAT_* via the site
llm client; no new config, no persistence.
"""

from __future__ import annotations


def build_messages(item: dict, existing_note: str = "") -> list[dict]:
    """System + user messages for drafting a note. `item` is the dict shape from
    app._item_dict (title/summary/keywords/author/type). When `existing_note` is
    non-empty it is shown so the draft complements rather than repeats it."""
    system = (
        '你是一个帮“我”做读书笔记的助手。我会给你一条 AI 领域内容的标题、摘要和关键词'
        "（注意：你只看得到摘要级别的信息，不是全文）。请据此起一份简洁的笔记骨架，"
        "供我之后补充。输出恰好三个 Markdown 小节，纯 Markdown，不要额外开场白或总结：\n"
        "## 要点\n（3-5 条要点，从摘要/关键词提炼，用无序列表）\n"
        "## 为什么值得记\n（1-2 句，这条内容对我可能的价值或独特角度）\n"
        "## 待探索\n（2-3 个这条内容引出但没回答的问题，用无序列表）\n"
        "具体、克制，不要空话套话。如果我已经写了笔记，只在已有内容之外补充，不要重复。"
    )
    kw = "、".join(item.get("keywords") or [])
    lines = [
        f"标题：{item.get('title', '')}",
        f"类型：{item.get('type', '')}",
        f"作者：{item.get('author', '')}",
        f"摘要：{item.get('summary', '')}",
    ]
    if kw:
        lines.append(f"关键词：{kw}")
    user = "\n".join(lines)
    if existing_note.strip():
        user += f"\n\n我已有笔记（请勿重复其内容）：\n{existing_note.strip()}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

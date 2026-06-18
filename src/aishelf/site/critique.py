"""Devil's-advocate critique prompt builder (pure), mirroring notedraft.py / collide.py.

Given an item's metadata (and any existing note), build the chat messages that ask
the model to argue *against* the content — its weakest point, the strongest opposing
case (steel-manned), and what would change the conclusion — and to push back on the
user's recorded take when there is one. The route does the lookup + streaming; this
module only phrases the prompt. Reuses ATLAS_CHAT_* via the site llm client; no new
config, no persistence.
"""

from __future__ import annotations


def build_messages(item: dict, note: str = "") -> list[dict]:
    """System + user messages for an adversarial critique. `item` is the dict shape
    from app._item_dict (title/summary/keywords/author/type). When `note` is
    non-empty it is shown and the model is told to challenge the user's take too."""
    system = (
        "你是一个爱抬杠但讲道理的批判者。我会给你一条 AI 领域内容的标题、摘要和关键词"
        "（你只看得到摘要级别的信息，不是全文）。请站在反方，对它唱个反调。"
        "输出恰好三段，每段以方括号小标题开头，每段不超过两句，要具体、有锋芒、对事不对人：\n"
        "【最薄弱的地方】它的论点或前提里最可能站不住、或被它忽略的一点。\n"
        "【反方会怎么说】把最强的反对立场讲出来——要 steel-man（替对方说出最有力的版本），"
        "不要稻草人。\n"
        "【什么能说服你改主意】一个具体的证据或观察，一旦出现就该改判。\n"
        "只输出这三段纯文本，不要使用 Markdown 语法（不要 # 或 * 等），不要额外开场白或总结。"
        "如果我附上了自己的笔记，也请顺带挑战我笔记里的看法。"
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
    if note.strip():
        user += f"\n\n我的笔记（也请一并挑战）：\n{note.strip()}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

"""RAG core for the Ask-your-library chat (pure, testable).

retrieve() runs the existing FTS5 search and attaches each item's note (loaded
fresh from disk). build_messages() turns the hits into a grounded system prompt
that forbids answering outside the provided sources. No LLM or HTTP here.
"""

from __future__ import annotations

from dataclasses import dataclass

from aishelf.db import search as db_search
from aishelf.site import notes

DEFAULT_K = 6
NAV_MAX = 5

_NAV_VERBS = (
    "打开", "播放", "跳转", "前往", "带我去", "查看", "我要看", "我想看", "想看",
    "打开看", "open", "play", "watch", "go to",
)
_VIDEO_CUES = ("视频", "video")
_BLOG_CUES = ("博客", "文章", "帖子", "blog", "article", "post")


@dataclass
class Source:
    id: str
    type: str
    title: str
    author: str
    platform: str
    summary: str
    keywords: list[str]
    note: str


def latest_user_question(messages: list[dict]) -> str:
    """The most recent user message's content as a string, or '' if there is
    none (also coerces a missing / None / non-string content to '')."""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _note_for(item_id: str) -> str:
    try:
        return notes.load_note(item_id)
    except ValueError:  # id not path-safe -> treat as no note
        return ""


def retrieve(db_path, question: str, *, k: int = DEFAULT_K) -> list[Source]:
    """Top-k FTS5 hits for the question, each enriched with its user note.

    Uses OR-mode search so conversational questions (with stop-words like 什么/是)
    still match relevant content via shared bigrams.
    """
    hits = db_search.search(db_path, question, limit=k, mode="or")
    return [
        Source(
            id=h.id, type=h.type, title=h.title, author=h.author,
            platform=h.platform, summary=h.summary, keywords=h.keywords,
            note=_note_for(h.id),
        )
        for h in hits
    ]


def source_refs(sources: list[Source]) -> list[dict]:
    """Minimal payload for the client's Sources panel (links by id + type)."""
    return [
        {"id": s.id, "type": s.type, "title": s.title, "author": s.author}
        for s in sources
    ]


def nav_types(question: str) -> set[str]:
    """The {video, blog} subset the user explicitly asks to open/view.

    A modality is included iff (any nav verb) AND (that modality's cue) appears.
    Empty set means no navigation intent. ASCII matching is case-insensitive;
    CJK is unaffected by lower().
    """
    q = (question or "").lower()
    if not any(v in q for v in _NAV_VERBS):
        return set()
    types: set[str] = set()
    if any(c in q for c in _VIDEO_CUES):
        types.add("video")
    if any(c in q for c in _BLOG_CUES):
        types.add("blog")
    return types


def nav_candidates(sources: list[Source], types: set[str]) -> list[Source]:
    """Sources whose type is requested, in retrieval order, capped at NAV_MAX."""
    if not types:
        return []
    return [s for s in sources if s.type in types][:NAV_MAX]


def nav_refs(candidates: list[Source]) -> list[dict]:
    """Card payload for the client (links + label decided client-side by type)."""
    return [
        {"id": s.id, "type": s.type, "title": s.title, "author": s.author,
         "platform": s.platform}
        for s in candidates
    ]


_RULES = (
    "你是 Atlas —— 用户个人 AI 内容库的问答助手。下面提供了从用户内容库中检索到的相关条目。\n"
    "规则：\n"
    "1. 只能依据下面提供的来源回答，不要使用来源之外的知识，也不要编造。\n"
    "2. 在某条来源支撑的说法后用 [n] 标注来源编号（可多个，如 [1][3]）。\n"
    "3. 如果这些来源不足以回答问题，直接说明“你的内容库里暂时没有相关内容”，并可建议去采集更多内容。\n"
    "4. 使用与用户提问相同的语言作答。\n"
)


def _format_sources(sources: list[Source]) -> str:
    if not sources:
        return "来源：\n（暂无检索到相关来源）\n"
    lines = ["来源："]
    for i, s in enumerate(sources, start=1):
        lines.append(f"[{i}] {s.title} — {s.author}，{s.platform}")
        lines.append(f"摘要：{s.summary}")
        if s.note:
            lines.append(f"用户笔记：{s.note}")
        lines.append("")
    return "\n".join(lines)


def build_messages(messages: list[dict], sources: list[Source]) -> list[dict]:
    """A grounded system prompt prepended to the client's conversation."""
    system = {"role": "system", "content": _RULES + "\n" + _format_sources(sources)}
    return [system] + list(messages)

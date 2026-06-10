"""RAG core for the Ask-your-library chat (pure, testable).

retrieve() runs the existing FTS5 search and attaches each item's note (loaded
fresh from disk). build_messages() turns the hits into a grounded system prompt
that forbids answering outside the provided sources. No LLM or HTTP here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aishelf import embed
from aishelf.db import search as db_search
from aishelf.db import tokenize, vector
from aishelf.site import notes

DEFAULT_K = 6
NAV_MAX = 5
RELEVANCE_FLOOR = 0.15
SIMILARITY_FLOOR = 0.30
CANDIDATE_N = 20

_CJK_NAV_VERBS = (
    "打开", "播放", "跳转", "前往", "带我去", "查看", "我要看", "我想看", "想看", "打开看",
)
# ASCII verbs need word boundaries so "play" doesn't match inside "display"/"replay".
_ASCII_NAV_RE = re.compile(r"\b(?:open|play|watch|go to)\b")
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
    """Top-k relevant sources for the question.

    Hybrid when an embedding service is configured/reachable: vector recall over
    the whole corpus (semantic / cross-lingual) unioned with FTS5 (exact-term
    safety net), re-ranked by cosine and floored. Falls back to pure FTS5 + the
    bigram-overlap floor when embeddings are unavailable — identical to before.
    """
    qv = embed.embed_query(question)
    if qv is None:
        return _retrieve_fts_only(db_path, question, k)
    return _retrieve_hybrid(db_path, question, qv, k)


def _source_from_hit(h) -> Source:
    return Source(
        id=h.id, type=h.type, title=h.title, author=h.author,
        platform=h.platform, summary=h.summary, keywords=h.keywords,
        note=_note_for(h.id),
    )


def _sources_for_ids(db_path, ids: list[str]) -> list[Source]:
    rows = db_search.get_by_ids(db_path, ids)
    return [_source_from_hit(rows[i]) for i in ids if i in rows]


def _retrieve_fts_only(db_path, question: str, k: int) -> list[Source]:
    hits = db_search.search(db_path, question, limit=k, mode="or")
    sources = [_source_from_hit(h) for h in hits]
    return relevant_sources(question, sources)


def _retrieve_hybrid(db_path, question: str, qv: list[float], k: int) -> list[Source]:
    ids, matrix = vector.load_embeddings(db_path, len(qv))
    ranked = vector.cosine_search(qv, ids, matrix, top_n=CANDIDATE_N)
    fts_hits = db_search.search(db_path, question, limit=CANDIDATE_N, mode="or")

    kept: list[str] = []
    seen: set[str] = set()
    for cid, score in ranked:                  # vector hits above the floor, cosine order
        if score >= SIMILARITY_FLOOR and cid not in seen:
            kept.append(cid)
            seen.add(cid)
    for h in fts_hits:                          # FTS exact hits append (bm25 order) — safety net
        if h.id not in seen:
            kept.append(h.id)
            seen.add(h.id)
    kept = kept[:k]
    return _sources_for_ids(db_path, kept)


def _question_bigrams(question: str) -> set[str]:
    return set(tokenize.bigrams(question).split())


def _source_text(s: Source) -> str:
    return " ".join([s.title, s.summary, " ".join(s.keywords), s.author, s.note])


def _overlap(q_bigrams: set[str], s: Source) -> float:
    """Fraction of the question's bigrams that appear in the source's text.
    Assumes q_bigrams is non-empty (callers guard the empty-question case)."""
    s_bigrams = set(tokenize.bigrams(_source_text(s)).split())
    return len(q_bigrams & s_bigrams) / len(q_bigrams)


def relevant_sources(question: str, sources: list[Source]) -> list[Source]:
    """Keep only sources sharing at least RELEVANCE_FLOOR of the question's
    bigrams, preserving retrieval order. Prunes the loosely-related tail that
    OR-mode retrieval lets through (items matching a single common bigram). An
    empty question has no bigrams, so nothing is considered relevant."""
    q_bigrams = _question_bigrams(question)
    if not q_bigrams:
        return []
    return [s for s in sources if _overlap(q_bigrams, s) >= RELEVANCE_FLOOR]


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
    if not (any(v in q for v in _CJK_NAV_VERBS) or _ASCII_NAV_RE.search(q)):
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


def is_low_confidence(question: str, sources: list[Source]) -> bool:
    """True when the library has nothing relevant: no sources, or the top source
    shares fewer than RELEVANCE_FLOOR of the question's bigrams. Pure heuristic —
    empty retrieval is the primary signal, overlap is a conservative secondary
    catch for loose OR-mode matches."""
    if not sources:
        return True
    q_bigrams = _question_bigrams(question)
    if not q_bigrams:
        return True
    return _overlap(q_bigrams, sources[0]) < RELEVANCE_FLOOR


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

"""CJK-aware tokenization for FTS5 full-text indexing and querying.

Text is stored/queried as bigrams: ASCII/digit runs kept whole (lowercased),
CJK runs split into overlapping 2-grams (a lone CJK char kept as-is). This lets
SQLite's plain unicode61 tokenizer match 2-character Chinese terms, which the
built-in trigram tokenizer cannot.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")


def _segment(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text or ""):
        if tok[0].isascii():
            out.append(tok.lower())
        elif len(tok) == 1:
            out.append(tok)
        else:
            out.extend(tok[i : i + 2] for i in range(len(tok) - 1))
    return out


def bigrams(text: str) -> str:
    """Space-joined bigram tokens for indexing."""
    return " ".join(_segment(text))


def to_match_query(user_q: str) -> str:
    """Build an FTS5 MATCH expression: AND of quoted bigrams. Empty if no tokens."""
    toks = _segment(user_q)
    if not toks:
        return ""
    return " AND ".join(f'"{t}"' for t in toks)

"""Full-text search over the derived DB (the consumption layer).

Bigram-encodes the query, runs an FTS5 MATCH ranked by bm25, and rehydrates
the structured row from `items`. Uses the FTS table name (not an alias) for
MATCH/bm25 — required by FTS5.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from aishelf.db import schema, tokenize

_OR = "or"
_AND = "and"

@dataclass
class SearchHit:
    id: str
    type: str
    title: str
    author: str
    platform: str
    source_url: str
    published_at: str
    summary: str
    keywords: list[str]


def _hit(row) -> SearchHit:
    return SearchHit(
        id=row["id"], type=row["type"], title=row["title"], author=row["author"],
        platform=row["platform"], source_url=row["source_url"],
        published_at=row["published_at"], summary=row["summary"],
        keywords=json.loads(row["keywords"]),
    )


def search(db_path, q, *, type=None, limit: int = 20, offset: int = 0, mode: str = _AND) -> list[SearchHit]:
    """Ranked full-text hits. Empty query (no tokens) -> [].

    `mode` controls whether bigrams are ANDed (default, exact) or ORed (lenient,
    useful for retrieval over conversational questions).
    """
    if mode not in (_AND, _OR):
        raise ValueError(f"mode must be {_AND!r} or {_OR!r}, got {mode!r}")
    if mode == _OR:
        match = tokenize.to_match_query_or(q)
    else:
        match = tokenize.to_match_query(q)
    if not match:
        return []
    con = schema.connect(db_path)
    try:
        schema.init_db(con)
        sql = (
            "SELECT i.* FROM items_fts JOIN items i ON i.id = items_fts.item_id "
            "WHERE items_fts MATCH :match"
        )
        params: dict = {"match": match}
        if type is not None:
            sql += " AND i.type = :type"
            params["type"] = type
        sql += " ORDER BY bm25(items_fts) LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset
        return [_hit(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()

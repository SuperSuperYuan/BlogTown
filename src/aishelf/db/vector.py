"""Pure vector storage + brute-force cosine search over the derived DB.

Embeddings are stored as float32 BLOBs in items.embedding. At a personal-library
scale (hundreds–low-thousands of rows) exhaustive cosine in numpy is sub-100 ms,
so there is no vector index. load_embeddings only returns rows whose dim matches
the query, sidestepping any cross-model dimension mismatch.
"""

from __future__ import annotations

import numpy as np

from aishelf.db import schema


def pack(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def unpack(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def load_embeddings(db_path, dim: int, *, type=None) -> tuple[list[str], np.ndarray]:
    """ids + an (N, dim) matrix for rows that have an embedding of this dim."""
    con = schema.connect(db_path)
    try:
        schema.init_db(con)
        sql = ("SELECT id, embedding FROM items "
               "WHERE embedding IS NOT NULL AND embedding_dim = :dim")
        params: dict = {"dim": dim}
        if type is not None:
            sql += " AND type = :type"
            params["type"] = type
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    if not rows:
        return [], np.empty((0, dim), dtype=np.float32)
    ids = [r["id"] for r in rows]
    mat = np.stack([unpack(r["embedding"]) for r in rows])
    return ids, mat


def cosine_search(query_vec, ids: list[str], matrix: np.ndarray, *, top_n: int) -> list[tuple[str, float]]:
    """(id, cosine) pairs, highest similarity first, capped at top_n."""
    if not ids:
        return []
    q = np.asarray(query_vec, dtype=np.float32)
    qn = float(np.linalg.norm(q))
    if qn == 0.0:
        return []
    norms = np.linalg.norm(matrix, axis=1)
    sims = (matrix @ q) / (norms * qn + 1e-12)
    order = np.argsort(-sims)[:top_n]
    return [(ids[i], float(sims[i])) for i in order]

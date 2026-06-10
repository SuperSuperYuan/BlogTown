"""Embedding client for semantic retrieval (self-hosted, OpenAI-compatible).

Reads ATLAS_EMBED_* with NO fallback to the chat/Hermes connection — the chat
provider (e.g. DeepSeek) does not serve embeddings. Unset ⇒ the feature is
disabled and every call returns None, so callers degrade to pure FTS5. Any
client/HTTP error is swallowed to None for the same reason (reads never crash).
"""

from __future__ import annotations

import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)


def get_embed_settings() -> dict[str, str] | None:
    base = os.environ.get("ATLAS_EMBED_BASE_URL")
    model = os.environ.get("ATLAS_EMBED_MODEL")
    if not base or not model:
        return None
    return {"base_url": base, "api_key": os.environ.get("ATLAS_EMBED_API_KEY", ""), "model": model}


def is_configured() -> bool:
    return get_embed_settings() is not None


def model_name() -> str | None:
    s = get_embed_settings()
    return s["model"] if s else None


def get_client(settings: dict[str, str]) -> OpenAI:
    return OpenAI(base_url=settings["base_url"], api_key=settings["api_key"] or "none", timeout=60.0)


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embeddings for a batch, or None if unconfigured / empty / on any error."""
    s = get_embed_settings()
    if s is None or not texts:
        return None
    try:
        client = get_client(s)
        resp = client.embeddings.create(model=s["model"], input=texts)
        return [d.embedding for d in resp.data]
    except Exception as exc:  # degrade to FTS5, never crash a read/sync
        logger.warning("embedding request failed: %s", exc)
        return None


def embed_query(text: str) -> list[float] | None:
    """Single-text convenience wrapper; None when unconfigured/empty/on error."""
    if not text:
        return None
    vecs = embed_texts([text])
    return vecs[0] if vecs else None

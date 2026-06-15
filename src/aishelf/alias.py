"""Short-alias client for graph node labels (LLM, OpenAI-compatible chat).

Reads ATLAS_CHAT_* (the same chat model that answers /ask, e.g. DeepSeek).
Unset ⇒ disabled (returns None). Any error or parse failure also returns None,
so callers fall back to a truncated title. Lives at the package root so the db
layer can use it without importing aishelf.site (mirrors embed.py).
"""

from __future__ import annotations

import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

ALIAS_BATCH_SIZE = 20
ALIAS_MAX_CHARS = 10  # safety cap; the prompt asks for <= 8

_PROMPT = (
    "为下列每条内容各起一个不超过8个汉字的简短中文别名，用于知识图谱的节点标签，"
    "要能概括主题、尽量短。只返回一个 JSON 字符串数组，元素顺序与输入编号一致，"
    "不要输出任何额外文字或解释。\n\n"
)


def get_alias_settings() -> dict[str, str] | None:
    base = os.environ.get("ATLAS_CHAT_BASE_URL")
    model = os.environ.get("ATLAS_CHAT_MODEL")
    if not base or not model:
        return None
    return {"base_url": base, "api_key": os.environ.get("ATLAS_CHAT_API_KEY", ""), "model": model}


def is_configured() -> bool:
    return get_alias_settings() is not None


def get_client(settings: dict[str, str]) -> OpenAI:
    return OpenAI(base_url=settings["base_url"], api_key=settings["api_key"] or "none", timeout=60.0)


def _extract_json_array(text: str) -> str:
    i = text.find("[")
    j = text.rfind("]")
    if i == -1 or j == -1 or j < i:
        raise ValueError("no JSON array in response")
    return text[i:j + 1]


def _clean(a: str) -> str:
    return (a or "").strip().strip('"「」""').strip()[:ALIAS_MAX_CHARS]


def generate_aliases(pairs: list[tuple[str, str]]) -> list[str] | None:
    """≤8-char aliases for (title, summary) pairs, or None if unconfigured /
    empty / on any error or parse mismatch. Batched (ALIAS_BATCH_SIZE per call);
    each batch must return a JSON array of the same length (all-or-nothing)."""
    s = get_alias_settings()
    if s is None or not pairs:
        return None
    try:
        client = get_client(s)
        out: list[str] = []
        for i in range(0, len(pairs), ALIAS_BATCH_SIZE):
            chunk = pairs[i:i + ALIAS_BATCH_SIZE]
            listing = "\n".join(
                f"{n + 1}. {title} ｜ {(summary or '')[:80]}"
                for n, (title, summary) in enumerate(chunk)
            )
            resp = client.chat.completions.create(
                model=s["model"],
                messages=[{"role": "user", "content": _PROMPT + listing}],
                stream=False,
            )
            content = resp.choices[0].message.content or ""
            arr = json.loads(_extract_json_array(content))
            if not isinstance(arr, list) or len(arr) != len(chunk):
                return None
            out.extend(_clean(str(x)) for x in arr)
        return out
    except Exception as exc:  # degrade to truncated-title fallback, never crash sync
        logger.warning("alias generation failed: %s", exc)
        return None

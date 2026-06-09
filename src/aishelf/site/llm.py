"""Chat-model connection for answering questions over the library.

Separate from `hermes` (the costly collection *agent*): this points at a plain
chat model via ATLAS_CHAT_*, each var defaulting to the matching Hermes setting
so zero extra config works out of the box. Reuses hermes.sse for SSE framing.
"""

from __future__ import annotations

import os
from typing import Iterator

from openai import APIConnectionError, APIError, APIStatusError, OpenAI

from aishelf.site import hermes


def get_chat_settings() -> dict[str, str]:
    h = hermes.get_settings()
    return {
        "base_url": os.environ.get("ATLAS_CHAT_BASE_URL", h["base_url"]),
        "api_key": os.environ.get("ATLAS_CHAT_API_KEY", h["api_key"]),
        "model": os.environ.get("ATLAS_CHAT_MODEL", h["model"]),
    }


def get_client(settings: dict[str, str] | None = None) -> OpenAI:
    s = settings or get_chat_settings()
    return OpenAI(base_url=s["base_url"], api_key=s["api_key"], timeout=120.0)


def stream_completion(messages: list[dict]) -> Iterator[str]:
    settings = get_chat_settings()
    client = get_client(settings)
    model = settings["model"]
    try:
        stream = client.chat.completions.create(model=model, messages=messages, stream=True)
        for chunk in stream:
            choices = chunk.choices
            if not choices:
                continue
            content = getattr(choices[0].delta, "content", None)
            if content:
                yield hermes.sse({"delta": content})
    except APIConnectionError:
        yield hermes.sse({"error": "无法连接对话模型，请确认服务正在运行"})
        return
    except APIStatusError as exc:
        yield hermes.sse({"error": f"对话模型返回错误状态 {exc.status_code}"})
        return
    except APIError as exc:
        yield hermes.sse({"error": f"对话模型调用出错：{exc}"})
        return
    except Exception as exc:  # never break the SSE stream silently
        yield hermes.sse({"error": f"处理对话模型响应时出错：{exc}"})
        return
    yield hermes.sse({"done": True})

"""Hermes agent connection and robust SSE streaming."""

from __future__ import annotations

import json
import os
from typing import Iterator

from openai import APIConnectionError, APIError, APIStatusError, OpenAI

DEFAULT_BASE_URL = "http://127.0.0.1:8642/v1"
DEFAULT_API_KEY = "EFd96sbMIobQK7pnHHEJ0Ri4VnfYNa_-rTcY8WiTZt4"
DEFAULT_MODEL = "hermes-agent"


def get_settings() -> dict[str, str]:
    return {
        "base_url": os.environ.get("HERMES_BASE_URL", DEFAULT_BASE_URL),
        "api_key": os.environ.get("HERMES_API_KEY", DEFAULT_API_KEY),
        "model": os.environ.get("HERMES_MODEL", DEFAULT_MODEL),
    }


def get_client() -> OpenAI:
    s = get_settings()
    # crawling can take a while, so allow a generous timeout
    return OpenAI(base_url=s["base_url"], api_key=s["api_key"], timeout=600.0)


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_chat(messages: list[dict]) -> Iterator[str]:
    client = get_client()
    model = get_settings()["model"]
    try:
        stream = client.chat.completions.create(model=model, messages=messages, stream=True)
        for chunk in stream:
            choices = chunk.choices
            if not choices:
                continue
            content = getattr(choices[0].delta, "content", None)
            if content:
                yield sse({"delta": content})
    except APIConnectionError:
        yield sse({"error": "无法连接 Hermes，请确认服务正在运行"})
        return
    except APIStatusError as exc:
        yield sse({"error": f"Hermes 返回错误状态 {exc.status_code}"})
        return
    except APIError as exc:
        yield sse({"error": f"Hermes 调用出错：{exc}"})
        return
    except Exception as exc:  # defense in depth: never break the SSE stream silently
        yield sse({"error": f"处理 Hermes 响应时出错：{exc}"})
        return
    yield sse({"done": True})

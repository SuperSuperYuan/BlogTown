#!/usr/bin/env python3
"""Connectivity smoke test for the local Hermes agent (OpenAI-compatible API).

Run it directly:

    python scripts/test_hermes.py
    python scripts/test_hermes.py "帮我爬取某个 up 主最近的视频"

Endpoint and key default to the local dev server but can be overridden via env:

    HERMES_BASE_URL   (default: http://127.0.0.1:8642/v1)
    HERMES_API_KEY    (default: the local dev key)
    HERMES_MODEL      (default: hermes-agent)
"""

from __future__ import annotations

import os
import sys

from openai import APIConnectionError, APIStatusError, OpenAI

BASE_URL = os.environ.get("HERMES_BASE_URL", "http://127.0.0.1:8642/v1")
API_KEY = os.environ.get(
    "HERMES_API_KEY", "EFd96sbMIobQK7pnHHEJ0Ri4VnfYNa_-rTcY8WiTZt4"
)
MODEL = os.environ.get("HERMES_MODEL", "hermes-agent")


def main() -> int:
    prompt = sys.argv[1] if len(sys.argv) > 1 else "你好，请用一句话介绍你自己。"

    print(f"→ endpoint: {BASE_URL}")
    print(f"→ model:    {MODEL}")
    print(f"→ prompt:   {prompt}\n")

    client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=60.0)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
    except APIConnectionError as exc:
        print(f"✗ 连接失败：无法访问 {BASE_URL}", file=sys.stderr)
        print(f"  请确认 Hermes server 正在运行。原始错误：{exc}", file=sys.stderr)
        return 1
    except APIStatusError as exc:
        print(f"✗ 服务返回错误状态 {exc.status_code}", file=sys.stderr)
        print(f"  {exc.response.text}", file=sys.stderr)
        return 1

    choice = response.choices[0]
    print("✓ 连接成功，收到回复：\n")
    print(choice.message.content)

    usage = response.usage
    if usage is not None:
        print(
            f"\n— tokens: prompt={usage.prompt_tokens} "
            f"completion={usage.completion_tokens} total={usage.total_tokens}"
        )
    print(f"— finish_reason: {choice.finish_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

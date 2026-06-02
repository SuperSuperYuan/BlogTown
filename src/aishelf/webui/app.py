"""FastAPI app: serve the chat page and proxy chat turns to Hermes over SSE."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from openai import APIConnectionError, APIError, APIStatusError
from pydantic import BaseModel

from aishelf.webui.config import get_client, get_settings

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Hermes WebUI")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_chat(messages: list[dict]) -> Iterator[str]:
    client = get_client()
    model = get_settings()["model"]
    try:
        stream = client.chat.completions.create(
            model=model, messages=messages, stream=True
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield _sse({"delta": delta})
    except APIConnectionError:
        yield _sse({"error": "无法连接 Hermes，请确认服务正在运行"})
        return
    except APIStatusError as exc:
        yield _sse({"error": f"Hermes 返回错误状态 {exc.status_code}"})
        return
    except APIError as exc:
        yield _sse({"error": f"Hermes 调用出错：{exc}"})
        return
    yield _sse({"done": True})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    payload = [m.model_dump() for m in req.messages]
    return StreamingResponse(_stream_chat(payload), media_type="text/event-stream")

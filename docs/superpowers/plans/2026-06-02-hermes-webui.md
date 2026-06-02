# Hermes WebUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web page where the user chats with their Hermes agent and sees replies stream in token-by-token.

**Architecture:** A thin FastAPI backend serves a single static HTML page and exposes `POST /api/chat`, which proxies the conversation to the Hermes OpenAI-compatible API with `stream=True` and relays deltas to the browser as Server-Sent Events. The API key stays server-side. The frontend is one vanilla HTML/JS file (no build step).

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, `openai` SDK, pydantic v2, pytest + FastAPI `TestClient`.

---

## File Structure

- Create: `src/aishelf/webui/__init__.py` — package marker.
- Create: `src/aishelf/webui/config.py` — read Hermes settings from env, build `OpenAI` client.
- Create: `src/aishelf/webui/app.py` — FastAPI app: `GET /` (serve page) + `POST /api/chat` (SSE proxy).
- Create: `src/aishelf/webui/static/index.html` — single-file chat frontend.
- Create: `src/aishelf/webui/__main__.py` — `python -m aishelf.webui` launcher.
- Create: `tests/unit/test_webui.py` — endpoint tests with the `openai` client mocked.
- Create: `tests/integration/test_webui_network.py` — live smoke test under the `network` marker.
- Modify: `pyproject.toml:10-17` — add `fastapi` and `uvicorn[standard]` to dependencies.

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml:10-17`

- [ ] **Step 1: Add fastapi + uvicorn to dependencies**

Replace the `dependencies` array (lines 10-17) with:

```toml
dependencies = [
  "yt-dlp>=2024.0.0",
  "youtube-transcript-api>=0.6.0",
  "openai>=1.0.0",
  "httpx>=0.27.0",
  "PyYAML>=6.0",
  "pydantic>=2.0",
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
]
```

- [ ] **Step 2: Install**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: installs `fastapi`, `uvicorn`, `starlette` with no errors.

- [ ] **Step 3: Verify import**

Run: `.venv/bin/python -c "import fastapi, uvicorn; print(fastapi.__version__)"`
Expected: prints a version like `0.x.y`, no ImportError.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add fastapi + uvicorn for hermes webui"
```

---

## Task 2: Config module

**Files:**
- Create: `src/aishelf/webui/__init__.py`
- Create: `src/aishelf/webui/config.py`
- Test: `tests/unit/test_webui.py`

- [ ] **Step 1: Create the package marker**

Create `src/aishelf/webui/__init__.py`:

```python
"""Hermes WebUI — a local chat page that proxies to the Hermes agent."""
```

- [ ] **Step 2: Write the failing test for settings defaults + overrides**

Create `tests/unit/test_webui.py`:

```python
from aishelf.webui import config


def test_get_settings_defaults(monkeypatch):
    for var in ("HERMES_BASE_URL", "HERMES_API_KEY", "HERMES_MODEL"):
        monkeypatch.delenv(var, raising=False)
    s = config.get_settings()
    assert s["base_url"] == "http://127.0.0.1:8642/v1"
    assert s["model"] == "hermes-agent"
    assert s["api_key"]  # non-empty default


def test_get_settings_env_override(monkeypatch):
    monkeypatch.setenv("HERMES_BASE_URL", "http://example/v1")
    monkeypatch.setenv("HERMES_API_KEY", "k")
    monkeypatch.setenv("HERMES_MODEL", "m")
    s = config.get_settings()
    assert s == {"base_url": "http://example/v1", "api_key": "k", "model": "m"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_webui.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aishelf.webui.config'`.

- [ ] **Step 4: Implement config**

Create `src/aishelf/webui/config.py`:

```python
"""Hermes connection settings, read from the environment.

Mirrors the env vars used by scripts/test_hermes.py so the dev defaults
match the already-verified local server.
"""

from __future__ import annotations

import os

from openai import OpenAI

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
    return OpenAI(base_url=s["base_url"], api_key=s["api_key"], timeout=120.0)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_webui.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/webui/__init__.py src/aishelf/webui/config.py tests/unit/test_webui.py
git commit -m "feat(webui): add hermes connection config"
```

---

## Task 3: FastAPI app with SSE chat endpoint

**Files:**
- Create: `src/aishelf/webui/app.py`
- Test: `tests/unit/test_webui.py`

The SSE wire format: each event is `data: <json>\n\n`, where the JSON is one of
`{"delta": "<text>"}`, `{"error": "<message>"}`, or `{"done": true}`.

- [ ] **Step 1: Add test helpers + failing tests for the chat endpoint**

Append to `tests/unit/test_webui.py`:

```python
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIStatusError

from aishelf.webui import app as webui_app


def _chunk(content):
    """Fake an OpenAI streaming chunk with one choice delta."""
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice])


class _FakeCompletions:
    def __init__(self, chunks=None, exc=None):
        self._chunks = chunks or []
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return iter(self._chunks)


class _FakeClient:
    def __init__(self, chunks=None, exc=None):
        self.chat = SimpleNamespace(completions=_FakeCompletions(chunks, exc))


def _events(resp):
    """Parse an SSE response body into a list of decoded JSON payloads."""
    out = []
    for block in resp.text.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            out.append(json.loads(block[len("data: "):]))
    return out


def _post(client, **kwargs):
    return client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}, **kwargs)


def test_chat_streams_deltas(monkeypatch):
    fake = _FakeClient(chunks=[_chunk("Hello"), _chunk(" world"), _chunk(None)])
    monkeypatch.setattr(webui_app, "get_client", lambda: fake)
    client = TestClient(webui_app.app)
    resp = _post(client)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _events(resp)
    assert {"delta": "Hello"} in events
    assert {"delta": " world"} in events
    assert {"done": True} in events
    # the None-content chunk must NOT produce a delta event
    assert {"delta": None} not in events


def test_chat_connection_error(monkeypatch):
    exc = APIConnectionError(request=httpx.Request("POST", "http://localhost"))
    monkeypatch.setattr(webui_app, "get_client", lambda: _FakeClient(exc=exc))
    client = TestClient(webui_app.app)
    resp = _post(client)
    assert resp.status_code == 200
    events = _events(resp)
    assert any("error" in e for e in events)


def test_chat_empty_messages(monkeypatch):
    monkeypatch.setattr(webui_app, "get_client", lambda: _FakeClient())
    client = TestClient(webui_app.app)
    resp = client.post("/api/chat", json={"messages": []})
    assert resp.status_code == 400


def test_index_served():
    client = TestClient(webui_app.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_webui.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aishelf.webui.app'`.

- [ ] **Step 3: Implement the app**

Create `src/aishelf/webui/app.py`:

```python
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
```

Note: `chat` is defined with `def` (not `async def`) so FastAPI runs the
blocking `openai` stream in a threadpool, and `_stream_chat` is a plain
generator. The `test_index_served` test will still fail until Task 4 creates
`index.html` — that is expected; the other three tests should pass now.

- [ ] **Step 4: Run the chat tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_webui.py -v -k "chat"`
Expected: PASS for `test_chat_streams_deltas`, `test_chat_connection_error`, `test_chat_empty_messages`.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/webui/app.py tests/unit/test_webui.py
git commit -m "feat(webui): add SSE chat endpoint proxying to hermes"
```

---

## Task 4: Frontend page

**Files:**
- Create: `src/aishelf/webui/static/index.html`
- Test: `tests/unit/test_webui.py::test_index_served` (already written in Task 3)

- [ ] **Step 1: Create the page**

Create `src/aishelf/webui/static/index.html`:

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Hermes Chat</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, -apple-system, sans-serif;
           background: #f5f5f7; display: flex; flex-direction: column; height: 100vh; }
    header { padding: 12px 16px; background: #1f2933; color: #fff; font-weight: 600; }
    #log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
    .msg { max-width: 75%; padding: 10px 14px; border-radius: 14px; white-space: pre-wrap;
           word-wrap: break-word; line-height: 1.5; }
    .user { align-self: flex-end; background: #0a84ff; color: #fff; }
    .assistant { align-self: flex-start; background: #fff; border: 1px solid #e2e2e2; }
    .assistant.error { background: #fff3f3; border-color: #ffb3b3; color: #b00020; }
    form { display: flex; gap: 8px; padding: 12px 16px; background: #fff; border-top: 1px solid #e2e2e2; }
    #input { flex: 1; padding: 10px 12px; border: 1px solid #ccc; border-radius: 10px; font-size: 15px; }
    button { padding: 10px 18px; border: none; border-radius: 10px; background: #0a84ff; color: #fff;
             font-size: 15px; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: default; }
  </style>
</head>
<body>
  <header>Hermes Chat</header>
  <div id="log"></div>
  <form id="form">
    <input id="input" autocomplete="off" placeholder="输入你的需求，例如：帮我爬某个 up 主最近的视频" />
    <button id="send" type="submit">发送</button>
  </form>
  <script>
    const log = document.getElementById("log");
    const form = document.getElementById("form");
    const input = document.getElementById("input");
    const sendBtn = document.getElementById("send");
    const messages = [];

    function bubble(cls, text) {
      const el = document.createElement("div");
      el.className = "msg " + cls;
      el.textContent = text;
      log.appendChild(el);
      log.scrollTop = log.scrollHeight;
      return el;
    }

    async function send(text) {
      messages.push({ role: "user", content: text });
      bubble("user", text);
      const assistantEl = bubble("assistant", "");
      let acc = "";

      let resp;
      try {
        resp = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages }),
        });
      } catch (e) {
        assistantEl.classList.add("error");
        assistantEl.textContent = "⚠️ 请求失败：" + e;
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          if (!raw.startsWith("data: ")) continue;
          let payload;
          try { payload = JSON.parse(raw.slice(6)); } catch { continue; }
          if (payload.delta) {
            acc += payload.delta;
            assistantEl.textContent = acc;
            log.scrollTop = log.scrollHeight;
          } else if (payload.error) {
            assistantEl.classList.add("error");
            assistantEl.textContent = "⚠️ " + payload.error;
          } else if (payload.done) {
            messages.push({ role: "assistant", content: acc });
          }
        }
      }
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      sendBtn.disabled = true;
      try {
        await send(text);
      } finally {
        sendBtn.disabled = false;
        input.focus();
      }
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: Run the index test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_webui.py::test_index_served -v`
Expected: PASS.

- [ ] **Step 3: Run the full unit suite**

Run: `.venv/bin/pytest tests/unit/test_webui.py -v`
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/aishelf/webui/static/index.html
git commit -m "feat(webui): add chat frontend page"
```

---

## Task 5: Launcher entry point

**Files:**
- Create: `src/aishelf/webui/__main__.py`

- [ ] **Step 1: Create the launcher**

Create `src/aishelf/webui/__main__.py`:

```python
"""Launch the Hermes WebUI: python -m aishelf.webui"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("HERMES_WEBUI_HOST", "127.0.0.1")
    port = int(os.environ.get("HERMES_WEBUI_PORT", "8000"))
    uvicorn.run("aishelf.webui.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the app object imports through the launcher path**

Run: `.venv/bin/python -c "from aishelf.webui.app import app; print(type(app).__name__)"`
Expected: prints `FastAPI`.

- [ ] **Step 3: Commit**

```bash
git add src/aishelf/webui/__main__.py
git commit -m "feat(webui): add python -m aishelf.webui launcher"
```

---

## Task 6: Network smoke test (live, opt-in)

**Files:**
- Create: `tests/integration/test_webui_network.py`

- [ ] **Step 1: Write the live smoke test**

Create `tests/integration/test_webui_network.py`:

```python
"""Live smoke test against a running Hermes server. Skipped unless `-m network`."""

import pytest
from fastapi.testclient import TestClient

from aishelf.webui.app import app

pytestmark = pytest.mark.network


def test_live_chat_round_trip():
    client = TestClient(app)
    resp = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "请只回复：ok"}]},
    )
    assert resp.status_code == 200
    deltas = [
        line for line in resp.text.splitlines()
        if line.startswith("data: ") and '"delta"' in line
    ]
    assert deltas, "expected at least one streamed delta from Hermes"
```

- [ ] **Step 2: Verify it is skipped by default**

Run: `.venv/bin/pytest tests/integration/test_webui_network.py -v`
Expected: 1 skipped (deselected by `-m "not network"`).

- [ ] **Step 3: (Optional) Run it live against the real server**

Run: `.venv/bin/pytest tests/integration/test_webui_network.py -v -m network`
Expected: PASS if the Hermes server is running on `http://127.0.0.1:8642/v1`.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_webui_network.py
git commit -m "test(webui): add live hermes smoke test under network marker"
```

---

## Task 7: Manual end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full default test suite**

Run: `.venv/bin/pytest -v`
Expected: all unit tests pass; network tests skipped.

- [ ] **Step 2: Start the server**

Run: `.venv/bin/python -m aishelf.webui`
Expected: uvicorn logs `Uvicorn running on http://127.0.0.1:8000`.

- [ ] **Step 3: Drive it in a browser**

Open `http://127.0.0.1:8000`, type "你好，请用一句话介绍你自己" and send.
Expected: an assistant bubble fills in token-by-token with Hermes's reply.

- [ ] **Step 4: Verify the error path**

Stop the Hermes server (or set `HERMES_BASE_URL` to a dead port and restart the
webui), then send a message.
Expected: a red error bubble "⚠️ 无法连接 Hermes，请确认服务正在运行" appears; the
page stays usable.

---

## Self-Review Notes

- **Spec coverage:** `GET /` (Task 3/4), `POST /api/chat` SSE (Task 3), env-var
  config (Task 2), key-stays-server-side (Task 2/3), error bubbles (Task 3 +
  frontend Task 4), `python -m aishelf.webui` (Task 5), mocked unit tests +
  network-marker smoke (Tasks 3/6), dependencies (Task 1) — all covered.
- **Wire format** (`data: {json}\n\n` with `delta`/`error`/`done`) is defined
  once in Task 3 and consumed identically by the frontend (Task 4) and tests.
- **Naming consistency:** `get_settings`, `get_client`, `_stream_chat`, `_sse`,
  `ChatRequest`, `Message` are used identically across app, tests, and launcher.

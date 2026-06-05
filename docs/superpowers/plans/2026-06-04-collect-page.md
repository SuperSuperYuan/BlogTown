# Collect Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/collect` chat page in the display site that forwards a user's request to the Hermes agent, which crawls and writes contract records directly into `data/`.

**Architecture:** The display-site backend gains a chat page and an SSE proxy endpoint. Each chat turn, the backend prepends a system instruction (absolute `data/` path + embedded JSON Schema + write rules) and streams the conversation to Hermes; Hermes writes the `data/{videos,blogs}/<id>.json` files itself. The old standalone `webui` package is deleted. Tests mock Hermes.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, `openai` SDK (streaming), pytest + `TestClient`.

**Spec:** `docs/superpowers/specs/2026-06-04-collect-page-design.md`

**Commands:** use `.venv/bin/python` / `.venv/bin/pytest`. Append to every commit body: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- Delete: `src/aishelf/webui/` (package), `tests/unit/test_webui.py`, `tests/integration/test_webui_network.py`.
- Create: `src/aishelf/site/hermes.py` — Hermes connection + `stream_chat` (robust SSE).
- Create: `src/aishelf/site/collect.py` — `build_collection_instructions`.
- Modify: `src/aishelf/site/app.py` — add `/collect` and `/collect/chat` routes.
- Modify: `src/aishelf/site/templates/base.html` — add「采集」nav link.
- Create: `src/aishelf/site/templates/collect.html` — the chat page.
- Modify: `src/aishelf/site/static/style.css` — chat styles.
- Create: `tests/unit/test_site_hermes.py`, `tests/unit/test_site_collect.py`.

---

## Task 1: Delete the old webui package

**Files:**
- Delete: `src/aishelf/webui/`, `tests/unit/test_webui.py`, `tests/integration/test_webui_network.py`

- [ ] **Step 1: Remove the package and its tests**

```bash
git rm -r src/aishelf/webui tests/unit/test_webui.py tests/integration/test_webui_network.py
```

- [ ] **Step 2: Verify the suite still passes without it**

Run: `.venv/bin/pytest -q`
Expected: passes (contract + site tests remain); no import errors referencing `aishelf.webui`.

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: remove standalone webui (chat moves into the display site)"
```

---

## Task 2: Hermes connection + streaming

**Files:**
- Create: `src/aishelf/site/hermes.py`
- Test: `tests/unit/test_site_hermes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_hermes.py`:

```python
import json
from types import SimpleNamespace

import httpx
from openai import APIConnectionError

from aishelf.site import hermes


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


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


def _events(chunks):
    out = []
    for piece in "".join(chunks).split("\n\n"):
        piece = piece.strip()
        if piece.startswith("data: "):
            out.append(json.loads(piece[len("data: "):]))
    return out


def test_stream_chat_yields_deltas_then_done(monkeypatch):
    fake = _FakeClient(chunks=[_chunk("Hi"), _chunk(None), _chunk(" there")])
    monkeypatch.setattr(hermes, "get_client", lambda: fake)
    events = _events(list(hermes.stream_chat([{"role": "user", "content": "x"}])))
    assert {"delta": "Hi"} in events
    assert {"delta": " there"} in events
    assert {"done": True} in events


def test_stream_chat_skips_chunks_without_choices(monkeypatch):
    none_chunk = SimpleNamespace(choices=None)
    fake = _FakeClient(chunks=[_chunk("a"), none_chunk, _chunk("b")])
    monkeypatch.setattr(hermes, "get_client", lambda: fake)
    events = _events(list(hermes.stream_chat([{"role": "user", "content": "x"}])))
    assert {"delta": "a"} in events and {"delta": "b"} in events
    assert not any("error" in e for e in events)


def test_stream_chat_connection_error_emits_error_event(monkeypatch):
    exc = APIConnectionError(request=httpx.Request("POST", "http://localhost"))
    monkeypatch.setattr(hermes, "get_client", lambda: _FakeClient(exc=exc))
    events = _events(list(hermes.stream_chat([{"role": "user", "content": "x"}])))
    assert any("error" in e for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_hermes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aishelf.site.hermes'`.

- [ ] **Step 3: Implement hermes.py**

Create `src/aishelf/site/hermes.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_hermes.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/hermes.py tests/unit/test_site_hermes.py
git commit -m "feat(site): add hermes connection + robust SSE streaming"
```

---

## Task 3: Collection instruction builder

**Files:**
- Create: `src/aishelf/site/collect.py`
- Test: `tests/unit/test_site_collect.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_collect.py`:

```python
from pathlib import Path

from aishelf.site.collect import build_collection_instructions


def test_instructions_contain_abs_paths_rules_and_schema(tmp_path):
    schema = tmp_path / "schema.json"
    schema.write_text('{"title": "ContentItem", "marker": "SCHEMA_BODY_123"}', encoding="utf-8")
    data_dir = tmp_path / "mydata"

    text = build_collection_instructions(data_dir, schema_path=schema)

    abs_data = str(data_dir.resolve())
    assert abs_data in text
    assert f"{abs_data}/videos/" in text
    assert f"{abs_data}/blogs/" in text
    # write conventions
    assert ".json.tmp" in text and "rename" in text
    # generated fields + content rules
    assert "summary" in text and "keywords" in text and "thumbnail_url" in text
    # the schema body is embedded verbatim
    assert "SCHEMA_BODY_123" in text


def test_default_schema_path_points_at_committed_schema():
    from aishelf.site import collect
    assert collect.SCHEMA_PATH.name == "content-item.schema.json"
    assert collect.SCHEMA_PATH.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_collect.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aishelf.site.collect'`.

- [ ] **Step 3: Implement collect.py**

Create `src/aishelf/site/collect.py`:

```python
"""Build the system instruction that tells Hermes how to write contract records."""

from __future__ import annotations

from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "docs" / "contract" / "content-item.schema.json"


def build_collection_instructions(data_dir, schema_path: Path = SCHEMA_PATH) -> str:
    base = Path(data_dir).resolve()
    schema_text = Path(schema_path).read_text(encoding="utf-8")
    return f"""你是 aishelf 的内容采集助手。根据用户的需求，使用你的浏览器/终端能力抓取对应的视频或博客信息，并把每一条结果写成符合下述契约的 JSON 文件。

写入位置（绝对路径，目录不存在请先创建）：
- 视频写到：{base}/videos/<id>.json
- 博客写到：{base}/blogs/<id>.json

id 规则：<平台>-<原站ID>，例如 youtube-<videoId>、bilibili-<bvid>；博客若无原生 ID，用 blog-<source_url 的 sha1 前 12 位>。文件名（去掉 .json）必须等于 JSON 里的 id 字段。

写入方式（原子写）：先写 <id>.json.tmp，再 rename 成 <id>.json；同 id 直接覆盖（幂等）。

内容规则：
- 视频只存元数据 + 链接（必含 thumbnail_url，有内嵌地址就填 embed_url），不要下载视频文件。
- 博客只存摘要 + 链接，不要存全文。
- summary（摘要）和 keywords（关键词）由你根据内容生成。
- published_at 用 ISO 8601（YYYY-MM-DD 或带时间）。

每条记录必须严格符合下面的 JSON Schema：

{schema_text}

完成后，用中文简要说明你写入了哪些条目（标题 + 文件路径）。"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_collect.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/collect.py tests/unit/test_site_collect.py
git commit -m "feat(site): add Hermes collection instruction builder"
```

---

## Task 4: Routes, chat page, nav, styles

**Files:**
- Modify: `src/aishelf/site/app.py`
- Modify: `src/aishelf/site/templates/base.html`
- Create: `src/aishelf/site/templates/collect.html`
- Modify: `src/aishelf/site/static/style.css`
- Test: `tests/unit/test_site_collect_routes.py`

- [ ] **Step 1: Write the failing route tests**

Create `tests/unit/test_site_collect_routes.py`:

```python
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    from aishelf.site.app import app
    return TestClient(app)


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks

    class _C:
        def __init__(self, chunks):
            self._chunks = chunks

        def create(self, **kwargs):
            return iter(self._chunks)

    @property
    def chat(self):
        return SimpleNamespace(completions=self._C(self._chunks))


def test_collect_page_renders(client):
    r = client.get("/collect")
    assert r.status_code == 200
    assert "采集" in r.text


def test_nav_has_collect_link(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/collect"' in r.text


def test_collect_chat_streams(client, monkeypatch):
    from aishelf.site import hermes
    monkeypatch.setattr(hermes, "get_client", lambda: _FakeClient([_chunk("done writing")]))
    r = client.post("/collect/chat", json={"messages": [{"role": "user", "content": "爬视频"}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "done writing" in r.text


def test_collect_chat_empty_messages_400(client):
    r = client.post("/collect/chat", json={"messages": []})
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_collect_routes.py -v`
Expected: FAIL — `404` for `/collect` (routes not added yet).

- [ ] **Step 3: Add imports and routes to app.py**

In `src/aishelf/site/app.py`, change the FastAPI imports block so it reads:

```python
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from aishelf.contract.loader import load_items
from aishelf.site import collect, hermes, views
from aishelf.site.config import get_data_dir
```

Then append these models and routes at the end of `src/aishelf/site/app.py`:

```python
class _Message(BaseModel):
    role: str
    content: str


class _ChatRequest(BaseModel):
    messages: list[_Message]


@app.get("/collect", response_class=HTMLResponse)
def collect_page(request: Request):
    return templates.TemplateResponse(request, "collect.html", {})


@app.post("/collect/chat")
def collect_chat(req: _ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    system = {"role": "system", "content": collect.build_collection_instructions(get_data_dir())}
    payload = [system] + [m.model_dump() for m in req.messages]
    return StreamingResponse(hermes.stream_chat(payload), media_type="text/event-stream")
```

- [ ] **Step 4: Add the「采集」nav link in base.html**

In `src/aishelf/site/templates/base.html`, replace the `<nav>` line with:

```html
    <nav><a href="/videos">视频</a><a href="/blogs">博客</a><a href="/collect">采集</a></nav>
```

- [ ] **Step 5: Create the chat page template**

Create `src/aishelf/site/templates/collect.html`:

```html
{% extends "base.html" %}
{% block title %}采集 · aishelf{% endblock %}
{% block content %}
<div class="collect">
  <h1>采集</h1>
  <p class="lead">描述你想采集的内容，例如：爬取 Karpathy 最近的视频。Hermes 会去抓取并写入，完成后到下面查看结果。</p>
  <div id="log" class="chatlog"></div>
  <form id="chatform" class="chatform">
    <input id="chatinput" autocomplete="off" placeholder="输入采集需求…" />
    <button type="submit" id="chatsend">发送</button>
  </form>
  <div class="resultlinks"><a class="btn" href="/videos">查看视频</a><a class="btn" href="/blogs">查看博客</a></div>
</div>
<script>
const log = document.getElementById("log");
const form = document.getElementById("chatform");
const input = document.getElementById("chatinput");
const sendBtn = document.getElementById("chatsend");
const messages = [];

function bubble(cls, text) {
  const el = document.createElement("div");
  el.className = "bubble " + cls;
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
    resp = await fetch("/collect/chat", {
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
  try { await send(text); } finally { sendBtn.disabled = false; input.focus(); }
});
</script>
{% endblock %}
```

- [ ] **Step 6: Add chat styles to style.css**

Append to `src/aishelf/site/static/style.css`:

```css
.collect .lead { color: #52606d; margin-bottom: 14px; }
.chatlog { display: flex; flex-direction: column; gap: 10px; min-height: 240px; max-height: 60vh; overflow-y: auto; background: #fff; border: 1px solid #e4e7eb; border-radius: 12px; padding: 16px; }
.bubble { max-width: 80%; padding: 10px 14px; border-radius: 14px; white-space: pre-wrap; word-wrap: break-word; line-height: 1.55; }
.bubble.user { align-self: flex-end; background: #0a84ff; color: #fff; }
.bubble.assistant { align-self: flex-start; background: #f0f2f5; }
.bubble.error { align-self: flex-start; background: #fff3f3; color: #b00020; border: 1px solid #ffb3b3; }
.chatform { display: flex; gap: 8px; margin-top: 12px; }
.chatform input { flex: 1; padding: 11px 14px; border: 1px solid #cbd2d9; border-radius: 10px; font-size: 15px; }
.chatform button { padding: 11px 20px; border: none; border-radius: 10px; background: #0a84ff; color: #fff; font-size: 15px; cursor: pointer; }
.chatform button:disabled { opacity: .5; cursor: default; }
.resultlinks { display: flex; gap: 10px; margin-top: 14px; }
```

- [ ] **Step 7: Run the route tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_collect_routes.py -v`
Expected: PASS (4 passed).

- [ ] **Step 8: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/base.html src/aishelf/site/templates/collect.html src/aishelf/site/static/style.css tests/unit/test_site_collect_routes.py
git commit -m "feat(site): add /collect chat page driving Hermes collection"
```

---

## Task 5: Full-suite verification + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the whole default suite**

Run: `.venv/bin/pytest -q`
Expected: all tests pass (contract + site + new collect tests); no references to the deleted `aishelf.webui`; network deselected.

- [ ] **Step 2: Start the site and smoke the page (no real Hermes needed)**

Run (background): `AISHELF_SITE_PORT=8001 .venv/bin/python -m aishelf.site`
Then: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/collect` and `curl -s http://127.0.0.1:8001/ | grep -c 'href="/collect"'`
Expected: `200`, and the grep count is `1`. Stop the server afterward.

---

## Self-Review Notes

- **Spec coverage:** delete old webui (Task 1); hermes connection + robust SSE incl. choices-None + error-event guards (Task 2); instruction builder with abs path + embedded schema + id/atomic-write/content rules (Task 3); `/collect` page + `/collect/chat` SSE proxy that prepends the system instruction + nav link + restyle + empty→400 (Task 4); verification + live smoke (Task 5). Result links 查看视频/查看博客 are in `collect.html` (Task 4 Step 5).
- **Name/type consistency:** `hermes.get_client` / `hermes.stream_chat` / `hermes.sse` are referenced identically in app.py and tests; `collect.build_collection_instructions(data_dir, schema_path)` and `collect.SCHEMA_PATH` match across app.py and tests. The SSE wire format (`data: {delta|error|done}\n\n`) produced by `hermes.stream_chat` is consumed identically by `collect.html`.
- **Starlette signature:** `TemplateResponse(request, "collect.html", {})` uses the modern positional form already adopted elsewhere in app.py.
- **Placeholder scan:** all code/template/CSS steps are complete; no TBD/TODO.
- **Path arithmetic:** `collect.py` at `src/aishelf/site/` → `parents[3]` = repo root → `docs/contract/content-item.schema.json` (exists, committed).

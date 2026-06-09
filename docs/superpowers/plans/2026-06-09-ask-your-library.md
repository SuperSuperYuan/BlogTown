# Ask-your-library (RAG chat) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/ask` chat that answers natural-language questions over the user's collected library — grounded in record summaries + the user's notes — using FTS5 retrieval over `atlas.db` and a separately-configured chat model, streaming answers with `[n]` citations and a linked Sources panel.

**Architecture:** Reuse the shipped FTS5 search (`aishelf.db`), the robust OpenAI-compatible SSE pattern (`aishelf.site.hermes`), and the `/collect` chat UI. A new `aishelf.site.llm` talks to a chat model (env `ATLAS_CHAT_*`, defaulting to the Hermes connection). A new pure `aishelf.site.ask` does retrieval + prompt building. Notes are folded into the FTS index so they are searchable; the note text also becomes grounding context. Two routes — `GET /ask` (page) and ungated `POST /ask/chat` (SSE) — mirror `/collect`.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, pydantic v2, SQLite + FTS5 (stdlib), `openai` SDK, pytest (LLM always mocked).

**Spec:** `docs/superpowers/specs/2026-06-09-ask-your-library-design.md`

---

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/aishelf/db/schema.py` | Modify | Add a `note` column to the `items_fts` FTS5 table. |
| `src/aishelf/db/sync.py` | Modify | Read each item's on-disk note, fold it into the FTS doc, and into the content hash (so a note change re-indexes). |
| `src/aishelf/site/llm.py` | Create | Chat-model connection (`ATLAS_CHAT_*`, default to Hermes) + robust `stream_completion`. |
| `src/aishelf/site/ask.py` | Create | Pure RAG core: `retrieve`, `build_messages`, `source_refs`, `latest_user_question`. |
| `src/aishelf/site/app.py` | Modify | `GET /ask` + `POST /ask/chat`; shared `_sync_db_async`; note route triggers a sync. |
| `src/aishelf/site/templates/ask.html` | Create | The Ask chat page (mirrors `/collect`, ungated, renders a Sources panel). |
| `src/aishelf/site/templates/base.html` | Modify | Add a nav link to `/ask`. |
| `src/aishelf/site/static/style.css` | Modify | Minimal styles for the Sources panel. |
| `tests/unit/test_db_sync.py` | Modify | Note-only match surfaces its item; note change re-indexes. |
| `tests/unit/test_site_llm.py` | Create | Chat settings defaults/override + streaming. |
| `tests/unit/test_site_ask.py` | Create | `build_messages`, `latest_user_question`, `source_refs`, `retrieve`. |
| `tests/unit/test_site_ask_routes.py` | Create | `/ask` page + `/ask/chat` route (mocked LLM). |
| `tests/unit/test_site_notes_routes.py` | Modify | Saving a note triggers the off-thread DB sync. |
| `README.md`, `docs/ARCHITECTURE.md` | Modify | Document `/ask`, `ATLAS_CHAT_*`, and the rebuild note. |

Run all tests with `pytest -q` (network deselected by default).

---

## Task 1: Fold notes into the FTS index

**Files:**
- Modify: `src/aishelf/db/schema.py:36-40`
- Modify: `src/aishelf/db/sync.py`
- Test: `tests/unit/test_db_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_db_sync.py` (the file already has `_write`, `_rows`, and imports `json`, `schema`, `sync`):

```python
def _write_note(data_dir, item_id, text):
    d = data_dir / "notes"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(
        json.dumps({"id": item_id, "text": text, "updated_at": "2024-01-03T00:00:00"}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_sync_indexes_note_text_for_search(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    # summary deliberately does NOT contain the term that's only in the note
    _write(data, "videos", "v1", summary="一段普通的摘要")
    _write_note(data, "v1", "里面讲到了向量数据库")
    sync(data, db)
    con = schema.connect(db)
    fts = con.execute("SELECT item_id FROM items_fts WHERE items_fts MATCH '\"向量\"'").fetchall()
    assert [r[0] for r in fts] == ["v1"]


def test_sync_reindexes_when_note_changes(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1", summary="普通摘要")
    sync(data, db)  # no note yet
    _write_note(data, "v1", "新增了关于强化学习的笔记")
    summary = sync(data, db)
    assert summary.updated == 1  # note change marks the item as updated
    con = schema.connect(db)
    fts = con.execute("SELECT item_id FROM items_fts WHERE items_fts MATCH '\"强化\"'").fetchall()
    assert [r[0] for r in fts] == ["v1"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_db_sync.py -q`
Expected: the two new tests FAIL (note text not in FTS; `updated` stays 0).

- [ ] **Step 3: Add the `note` column to the FTS schema**

In `src/aishelf/db/schema.py`, change the `items_fts` definition:

```python
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  item_id UNINDEXED,
  title, summary, keywords, author, note,
  tokenize='unicode61'
);
```

- [ ] **Step 4: Read notes in sync and fold them in**

In `src/aishelf/db/sync.py`, add `from pathlib import Path` near the top imports, then add this helper above `_content_hash`:

```python
def _note_text(data_dir, item_id: str) -> str:
    """The user's note for an item, or '' if none/unreadable. Read by data_dir
    (not the env) so sync stays self-contained on its argument."""
    path = Path(data_dir) / "notes" / f"{item_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("text", "")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""
```

Change `_content_hash` to incorporate the note so a note-only change re-indexes:

```python
def _content_hash(item, note: str = "") -> str:
    blob = json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1((blob + "\x00" + note).encode("utf-8")).hexdigest()
```

In the `sync` loop, compute the note, pass it to the hash, and add it to the FTS insert. Replace the loop body's top + the FTS insert:

```python
        for it in items:
            seen.add(it.id)
            note = _note_text(data_dir, it.id)
            h = _content_hash(it, note)
            if existing.get(it.id) == h:
                summary.unchanged += 1
                continue
            con.execute(upsert_sql, _row(it, h, synced_at))
            con.execute("DELETE FROM items_fts WHERE item_id = ?", (it.id,))
            con.execute(
                "INSERT INTO items_fts (item_id, title, summary, keywords, author, note) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    it.id,
                    tokenize.bigrams(it.title),
                    tokenize.bigrams(it.summary),
                    tokenize.bigrams(" ".join(it.keywords)),
                    tokenize.bigrams(it.author),
                    tokenize.bigrams(note),
                ),
            )
            if it.id in existing:
                summary.updated += 1
            else:
                summary.added += 1
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_db_sync.py -q`
Expected: PASS (all sync tests, including the two new ones).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/db/schema.py src/aishelf/db/sync.py tests/unit/test_db_sync.py
git commit -m "feat(db): index user notes into items_fts so notes are searchable

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Chat-model client (`aishelf.site.llm`)

**Files:**
- Create: `src/aishelf/site/llm.py`
- Test: `tests/unit/test_site_llm.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_llm.py`:

```python
from types import SimpleNamespace

from aishelf.site import llm


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.captured = {}
        parent = self

        class _Completions:
            def create(self, **kwargs):
                parent.captured = kwargs
                return iter(parent._chunks)

        self.chat = SimpleNamespace(completions=_Completions())


def test_chat_settings_default_to_hermes(monkeypatch):
    for k in ("ATLAS_CHAT_BASE_URL", "ATLAS_CHAT_API_KEY", "ATLAS_CHAT_MODEL",
              "HERMES_BASE_URL", "HERMES_API_KEY", "HERMES_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HERMES_BASE_URL", "http://hermes:9/v1")
    monkeypatch.setenv("HERMES_MODEL", "hermes-agent")
    s = llm.get_chat_settings()
    assert s["base_url"] == "http://hermes:9/v1"
    assert s["model"] == "hermes-agent"


def test_chat_settings_override(monkeypatch):
    monkeypatch.setenv("ATLAS_CHAT_BASE_URL", "http://chat:1/v1")
    monkeypatch.setenv("ATLAS_CHAT_MODEL", "fast-chat")
    s = llm.get_chat_settings()
    assert s["base_url"] == "http://chat:1/v1"
    assert s["model"] == "fast-chat"


def test_stream_completion_yields_delta_and_done(monkeypatch):
    monkeypatch.setattr(llm, "get_client", lambda: _FakeClient([_chunk("你好"), _chunk("世界")]))
    out = "".join(llm.stream_completion([{"role": "user", "content": "hi"}]))
    assert "你好" in out and "世界" in out
    assert '"done": true' in out


def test_stream_completion_error_event(monkeypatch):
    class _Boom:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(
                create=lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))))
    monkeypatch.setattr(llm, "get_client", lambda: _Boom())
    out = "".join(llm.stream_completion([{"role": "user", "content": "hi"}]))
    assert '"error"' in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_site_llm.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'aishelf.site.llm'`.

- [ ] **Step 3: Implement `llm.py`**

Create `src/aishelf/site/llm.py`:

```python
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


def get_client() -> OpenAI:
    s = get_chat_settings()
    return OpenAI(base_url=s["base_url"], api_key=s["api_key"], timeout=120.0)


def stream_completion(messages: list[dict]) -> Iterator[str]:
    client = get_client()
    model = get_chat_settings()["model"]
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_site_llm.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/llm.py tests/unit/test_site_llm.py
git commit -m "feat(site): chat-model client (ATLAS_CHAT_*, defaults to Hermes)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: RAG core (`aishelf.site.ask`)

**Files:**
- Create: `src/aishelf/site/ask.py`
- Test: `tests/unit/test_site_ask.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_ask.py`:

```python
import json

from aishelf.site import ask
from aishelf.site.ask import Source


def _src(i, note=""):
    return Source(id=f"v{i}", type="video", title=f"标题{i}", author="作者甲",
                  platform="youtube", summary=f"摘要{i}", keywords=["k"], note=note)


def test_latest_user_question_returns_last_user_message():
    msgs = [{"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "答"},
            {"role": "user", "content": "第二问"}]
    assert ask.latest_user_question(msgs) == "第二问"


def test_latest_user_question_empty_when_none():
    assert ask.latest_user_question([{"role": "assistant", "content": "x"}]) == ""


def test_build_messages_includes_numbered_sources_note_and_guard():
    msgs = [{"role": "user", "content": "讲了什么？"}]
    out = ask.build_messages(msgs, [_src(1, note="我的笔记内容")])
    assert out[0]["role"] == "system"
    sys = out[0]["content"]
    assert "[1]" in sys and "标题1" in sys
    assert "我的笔记内容" in sys          # the user's note is included as grounding
    assert "[n]" in sys                    # citation instruction present
    assert "内容库" in sys                  # no-source guard wording present
    assert out[1:] == msgs                 # history + question preserved after system


def test_build_messages_marks_empty_sources():
    msgs = [{"role": "user", "content": "x"}]
    out = ask.build_messages(msgs, [])
    assert "暂无" in out[0]["content"]      # explicit "no sources retrieved" marker
    assert out[1:] == msgs


def test_source_refs_shape():
    refs = ask.source_refs([_src(1), _src(2)])
    assert refs == [
        {"id": "v1", "type": "video", "title": "标题1", "author": "作者甲"},
        {"id": "v2", "type": "video", "title": "标题2", "author": "作者甲"},
    ]


def test_retrieve_finds_note_only_match(tmp_path, monkeypatch):
    # an item whose summary lacks the term, but whose note contains it
    data = tmp_path / "data"
    (data / "videos").mkdir(parents=True)
    rec = {"id": "v1", "type": "video", "title": "标题", "author": "作者甲",
           "platform": "youtube", "source_url": "https://x/v1", "published_at": "2024-01-01",
           "summary": "普通摘要", "keywords": [], "collected_at": "2024-01-02T00:00:00",
           "thumbnail_url": "https://img/x.jpg"}
    (data / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    (data / "notes").mkdir()
    (data / "notes" / "v1.json").write_text(
        json.dumps({"id": "v1", "text": "讲到了向量数据库", "updated_at": "2024-01-03"}, ensure_ascii=False),
        encoding="utf-8")
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    from aishelf.db.sync import sync
    db = tmp_path / "atlas.db"
    sync(data, db)
    sources = ask.retrieve(db, "向量", k=5)
    assert [s.id for s in sources] == ["v1"]
    assert sources[0].note == "讲到了向量数据库"   # note loaded fresh into the source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_site_ask.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'aishelf.site.ask'`.

- [ ] **Step 3: Implement `ask.py`**

Create `src/aishelf/site/ask.py`:

```python
"""RAG core for the Ask-your-library chat (pure, testable).

retrieve() runs the existing FTS5 search and attaches each item's note (loaded
fresh from disk). build_messages() turns the hits into a grounded system prompt
that forbids answering outside the provided sources. No LLM or HTTP here.
"""

from __future__ import annotations

from dataclasses import dataclass

from aishelf.db import search as db_search
from aishelf.site import notes

DEFAULT_K = 6


@dataclass
class Source:
    id: str
    type: str
    title: str
    author: str
    platform: str
    summary: str
    keywords: list[str]
    note: str


def latest_user_question(messages: list[dict]) -> str:
    """The most recent user message's content, or '' if there is none."""
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def _note_for(item_id: str) -> str:
    try:
        return notes.load_note(item_id)
    except ValueError:  # id not path-safe -> treat as no note
        return ""


def retrieve(db_path, question: str, *, k: int = DEFAULT_K) -> list[Source]:
    """Top-k FTS5 hits for the question, each enriched with its user note."""
    hits = db_search.search(db_path, question, limit=k)
    return [
        Source(
            id=h.id, type=h.type, title=h.title, author=h.author,
            platform=h.platform, summary=h.summary, keywords=h.keywords,
            note=_note_for(h.id),
        )
        for h in hits
    ]


def source_refs(sources: list[Source]) -> list[dict]:
    """Minimal payload for the client's Sources panel (links by id + type)."""
    return [
        {"id": s.id, "type": s.type, "title": s.title, "author": s.author}
        for s in sources
    ]


_RULES = (
    "你是 Atlas —— 用户个人 AI 内容库的问答助手。下面提供了从用户内容库中检索到的相关条目。\n"
    "规则：\n"
    "1. 只能依据下面提供的来源回答，不要使用来源之外的知识，也不要编造。\n"
    "2. 在某条来源支撑的说法后用 [n] 标注来源编号（可多个，如 [1][3]）。\n"
    "3. 如果这些来源不足以回答问题，直接说明“你的内容库里暂时没有相关内容”，并可建议去采集更多内容。\n"
    "4. 使用与用户提问相同的语言作答。\n"
)


def _format_sources(sources: list[Source]) -> str:
    if not sources:
        return "来源：\n（暂无检索到相关来源）\n"
    lines = ["来源："]
    for i, s in enumerate(sources, start=1):
        lines.append(f"[{i}] {s.title} — {s.author}，{s.platform}")
        lines.append(f"摘要：{s.summary}")
        if s.note:
            lines.append(f"用户笔记：{s.note}")
        lines.append("")
    return "\n".join(lines)


def build_messages(messages: list[dict], sources: list[Source]) -> list[dict]:
    """A grounded system prompt prepended to the client's conversation."""
    system = {"role": "system", "content": _RULES + "\n" + _format_sources(sources)}
    return [system] + list(messages)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_site_ask.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/ask.py tests/unit/test_site_ask.py
git commit -m "feat(site): RAG core (retrieve + grounded prompt builder) for /ask

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Routes `/ask` + `/ask/chat` and shared DB-sync helper

**Files:**
- Modify: `src/aishelf/site/app.py`
- Test: `tests/unit/test_site_ask_routes.py`
- Test: `tests/unit/test_site_notes_routes.py`

- [ ] **Step 1: Write the failing route tests**

Create `tests/unit/test_site_ask_routes.py`:

```python
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def _write(data_dir, sub, item_id, title, summary="摘要"):
    rec = {
        "id": item_id, "type": "video" if sub == "videos" else "blog",
        "title": title, "author": "作者甲",
        "platform": "youtube" if sub == "videos" else "blog",
        "source_url": f"https://x/{item_id}", "published_at": "2024-01-01",
        "summary": summary, "keywords": [], "collected_at": "2024-01-02T00:00:00",
    }
    if sub == "videos":
        rec["thumbnail_url"] = "https://img/x.jpg"
    d = data_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    _write(tmp_path, "videos", "v1", "大语言模型与检索增强")
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")
    from aishelf.site.app import app
    return TestClient(app)


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.captured = {}
        parent = self

        class _Completions:
            def create(self, **kwargs):
                parent.captured = kwargs
                return iter(parent._chunks)

        self.chat = SimpleNamespace(completions=_Completions())


def test_ask_page_renders(client):
    r = client.get("/ask")
    assert r.status_code == 200
    assert "/ask/chat" in r.text
    assert "renderSources" in r.text


def test_nav_has_ask_link(client):
    r = client.get("/")
    assert 'href="/ask"' in r.text


def test_ask_chat_streams_answer_and_sources(client, monkeypatch):
    from aishelf.site import llm
    monkeypatch.setattr(llm, "get_client", lambda: _FakeClient([_chunk("检索增强是…")]))
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "什么是检索增强"}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "检索增强是…" in r.text     # streamed answer
    assert '"sources"' in r.text       # a sources event was emitted
    assert "v1" in r.text              # the retrieved item id is in the sources payload


def test_ask_chat_grounds_prompt_on_retrieved_sources(client, monkeypatch):
    from aishelf.site import llm
    fake = _FakeClient([_chunk("ok")])
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "检索"}]})
    assert r.status_code == 200
    sent = fake.captured["messages"]
    assert sent[0]["role"] == "system"
    assert "大语言模型与检索增强" in sent[0]["content"]  # retrieved source is in the grounded prompt
    assert sent[-1] == {"role": "user", "content": "检索"}


def test_ask_chat_empty_messages_400(client):
    r = client.post("/ask/chat", json={"messages": []})
    assert r.status_code == 400


def test_ask_chat_is_ungated(client, monkeypatch):
    # no X-Collect-Token header is needed; the LLM is reached
    from aishelf.site import llm
    monkeypatch.setattr(llm, "get_client", lambda: _FakeClient([_chunk("ans")]))
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert "ans" in r.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_site_ask_routes.py -q`
Expected: FAIL (404 for `/ask`, no `/ask/chat` route).

- [ ] **Step 3: Add a shared async-sync helper and refactor `collect_chat`**

In `src/aishelf/site/app.py`, add `ask` and `llm` to the `aishelf.site` import block:

```python
from aishelf.site import (
    allowlist,
    ask,
    collect,
    hermes,
    items,
    llm,
    notes,
    schedule_state,
    scheduler,
    schedules,
    views,
)
```

Add this helper just after `_items()` (near line 109):

```python
def _sync_db_async(data_dir) -> None:
    """Refresh the derived DB off the request thread (it's a recoverable view)."""
    def _bg():
        try:
            db_sync.sync(data_dir, default_db_path(data_dir))
        except Exception as exc:  # derived DB; never surface to the caller
            logger.warning("background DB sync failed: %s", exc)
    threading.Thread(target=_bg, name="aishelf-db-sync", daemon=True).start()
```

Replace `collect_chat`'s inner `_with_sync` (lines ~243-254) to reuse the helper:

```python
    def _with_sync():
        try:
            yield from stream
        finally:
            # Hermes wrote files during the turn; refresh the derived DB.
            _sync_db_async(data_dir)
```

- [ ] **Step 4: Add the `/ask` and `/ask/chat` routes**

In `src/aishelf/site/app.py`, add after the `search_page` route (before the `_Message`/`_ChatRequest` models are fine too, but place after `collect_chat` for locality). The `_ChatRequest` model already exists and is reused:

```python
@app.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request):
    return templates.TemplateResponse(request, "ask.html", {})


@app.post("/ask/chat")
def ask_chat(req: _ChatRequest):
    # Ungated: answering is cheap relative to collection and is core "reading" use.
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")
    data_dir = get_data_dir()
    messages = [m.model_dump() for m in req.messages]
    question = ask.latest_user_question(messages)
    sources = ask.retrieve(default_db_path(data_dir), question)
    payload = ask.build_messages(messages, sources)

    def _gen():
        # Emit the sources first so the client can render the panel immediately.
        yield hermes.sse({"sources": ask.source_refs(sources)})
        yield from llm.stream_completion(payload)

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

- [ ] **Step 5: Make the note route refresh the index**

Replace `save_note_route` (lines ~327-333) so a saved note becomes searchable:

```python
@app.post("/notes/{item_id}")
def save_note_route(item_id: str, req: _NoteRequest):
    try:
        updated_at = notes.save_note(item_id, req.text)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid note id")
    # The note text feeds search; refresh the derived index off-thread.
    _sync_db_async(get_data_dir())
    return {"ok": True, "updated_at": updated_at}
```

- [ ] **Step 6: Add the note-route sync test**

Append to `tests/unit/test_site_notes_routes.py`:

```python
def test_saving_note_triggers_db_sync(client, monkeypatch):
    import threading

    from aishelf.db import sync as db_sync

    done = threading.Event()
    monkeypatch.setattr(db_sync, "sync", lambda data_dir, db_path: done.set())

    r = client.post("/notes/youtube-aaa", json={"text": "让笔记进入搜索索引"})
    assert r.status_code == 200
    assert done.wait(timeout=5)  # background sync ran after the note was saved
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/unit/test_site_ask_routes.py tests/unit/test_site_notes_routes.py tests/unit/test_site_collect_routes.py -q`
Expected: PASS (new ask routes, the note-sync test, and the existing collect-sync test still green after the refactor).

- [ ] **Step 8: Commit**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_ask_routes.py tests/unit/test_site_notes_routes.py
git commit -m "feat(site): /ask + /ask/chat routes; sync index after note saves

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Ask chat page + nav link + styles

**Files:**
- Create: `src/aishelf/site/templates/ask.html`
- Modify: `src/aishelf/site/templates/base.html:12`
- Modify: `src/aishelf/site/static/style.css`

Note: the rendering assertions (`/ask/chat`, `renderSources`, nav link) are covered by Task 4's `test_ask_page_renders` / `test_nav_has_ask_link`. This task makes them pass.

- [ ] **Step 1: Run the page tests to confirm they fail**

Run: `pytest tests/unit/test_site_ask_routes.py::test_ask_page_renders tests/unit/test_site_ask_routes.py::test_nav_has_ask_link -q`
Expected: FAIL (template `ask.html` does not exist / no nav link).

- [ ] **Step 2: Add the nav link**

In `src/aishelf/site/templates/base.html`, change the nav line:

```html
    <nav><a href="/videos">视频</a><a href="/blogs">博客</a><a href="/ask">问答</a><a href="/collect">Hermes</a></nav>
```

- [ ] **Step 3: Create `ask.html`**

Create `src/aishelf/site/templates/ask.html`:

```html
{% extends "base.html" %}
{% block title %}问答 · Atlas{% endblock %}
{% block content %}
<div class="hermes">
  <div class="hermes-main">
  <section class="card hermes-intro">
    <header class="hermes-head">
      <div class="hermes-avatar">A</div>
      <div class="hermes-head-text">
        <h1>问答</h1>
        <p class="lead">基于你收藏的视频 / 博客摘要与你的笔记来回答问题，并给出可点击的来源。</p>
      </div>
    </header>
  </section>

  <section class="card chat-card">
    <div id="log" class="chatlog"></div>

    <div id="examples" class="examples">
      <span class="examples-label">试试：</span>
      <button type="button" class="chip">我收藏的内容里关于 RAG 有哪些观点？</button>
      <button type="button" class="chip">总结一下我看过的 agent 相关视频</button>
    </div>

    <form id="chatform" class="composer">
      <textarea id="chatinput" rows="1" placeholder="问关于你内容库的问题，Enter 发送，Shift+Enter 换行…"></textarea>
      <button type="submit" id="chatsend" class="send" title="发送" aria-label="发送">➤</button>
    </form>

    <div class="actionbar">
      <button id="chatclear" type="button" class="ghost">清除对话</button>
      <span class="spacer"></span>
      <a class="textlink" href="/videos">查看视频</a>
      <a class="textlink" href="/blogs">查看博客</a>
    </div>
  </section>
  </div>
</div>
<script>
const STORAGE_KEY = "aishelf_ask_history";
const log = document.getElementById("log");
const form = document.getElementById("chatform");
const input = document.getElementById("chatinput");
const sendBtn = document.getElementById("chatsend");
const clearBtn = document.getElementById("chatclear");
const examples = document.getElementById("examples");

function loadHistory() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || []; }
  catch { return []; }
}
function saveHistory() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
}
const messages = loadHistory();

function bubble(cls, text) {
  const row = document.createElement("div");
  row.className = "msg " + cls;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = cls === "user" ? "我" : "A";
  const body = document.createElement("div");
  body.className = "bubble " + cls;
  body.textContent = text;
  row.append(avatar, body);
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return body;
}

function showTyping(el) {
  el.classList.add("typing");
  el.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
}

// Render a "来源" panel of links beneath the answer bubble.
function renderSources(afterEl, sources) {
  if (!sources || !sources.length) return;
  const box = document.createElement("div");
  box.className = "sources";
  const label = document.createElement("div");
  label.className = "sources-label";
  label.textContent = "来源";
  box.appendChild(label);
  sources.forEach((s, i) => {
    const a = document.createElement("a");
    a.className = "source-link";
    a.href = (s.type === "video" ? "/videos/" : "/blogs/") + encodeURIComponent(s.id);
    a.textContent = "[" + (i + 1) + "] " + s.title + " — " + s.author;
    box.appendChild(a);
  });
  afterEl.insertAdjacentElement("afterend", box);
}

function updateExamples() {
  examples.style.display = messages.length ? "none" : "flex";
}

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 200) + "px";
}
input.addEventListener("input", autosize);

for (const m of messages) {
  bubble(m.role === "user" ? "user" : "assistant", m.content);
}
updateExamples();

async function send(text) {
  messages.push({ role: "user", content: text });
  saveHistory();
  updateExamples();
  bubble("user", text);
  const assistantEl = bubble("assistant", "");
  showTyping(assistantEl);
  let acc = "";
  let streaming = false;

  function fail(msg) {
    assistantEl.classList.remove("typing", "streaming");
    assistantEl.classList.add("error");
    assistantEl.textContent = msg;
  }

  let resp;
  try {
    resp = await fetch("/ask/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    });
  } catch (e) {
    fail("⚠️ 请求失败：" + e);
    return;
  }
  if (!resp.ok || !resp.body) {
    fail("⚠️ 请求失败：HTTP " + resp.status);
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
      if (payload.sources) {
        renderSources(assistantEl, payload.sources);
      } else if (payload.delta) {
        if (!streaming) {
          streaming = true;
          assistantEl.classList.remove("typing");
          assistantEl.classList.add("streaming");
        }
        acc += payload.delta;
        assistantEl.textContent = acc;
        log.scrollTop = log.scrollHeight;
      } else if (payload.error) {
        fail("⚠️ " + payload.error);
      } else if (payload.done) {
        assistantEl.classList.remove("typing", "streaming");
        messages.push({ role: "assistant", content: acc });
        saveHistory();
      }
    }
  }
  assistantEl.classList.remove("typing", "streaming");
}

function submitCurrent() {
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  autosize();
  sendBtn.disabled = true;
  send(text).finally(() => { sendBtn.disabled = false; input.focus(); });
}

form.addEventListener("submit", (e) => { e.preventDefault(); submitCurrent(); });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitCurrent(); }
});
for (const chip of examples.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => { input.value = chip.textContent; autosize(); input.focus(); });
}
clearBtn.addEventListener("click", () => {
  messages.length = 0;
  localStorage.removeItem(STORAGE_KEY);
  log.innerHTML = "";
  updateExamples();
});
</script>
{% endblock %}
```

- [ ] **Step 4: Add Sources styles**

Append to `src/aishelf/site/static/style.css`:

```css
/* Ask: sources panel under an answer */
.sources { margin: 6px 0 14px 52px; display: flex; flex-direction: column; gap: 4px; }
.sources-label { font-size: 12px; color: #888; }
.source-link { font-size: 13px; color: #2d6cdf; text-decoration: none; }
.source-link:hover { text-decoration: underline; }
```

- [ ] **Step 5: Run the page tests to verify they pass**

Run: `pytest tests/unit/test_site_ask_routes.py -q`
Expected: PASS (all ask-route tests, including page render + nav link).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/site/templates/ask.html src/aishelf/site/templates/base.html src/aishelf/site/static/style.css
git commit -m "feat(site): Ask chat page with sources panel + nav link

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Docs + full test sweep

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CLAUDE.md` (config + module list)

- [ ] **Step 1: Run the full suite (baseline before docs)**

Run: `pytest -q`
Expected: all tests PASS (previously 169 + the new tests).

- [ ] **Step 2: Update README**

In `README.md`, add a row to the Configuration table (after the `AISHELF_DB_PATH` row):

```markdown
| `ATLAS_CHAT_BASE_URL` / `ATLAS_CHAT_API_KEY` / `ATLAS_CHAT_MODEL` | = the matching `HERMES_*` | Chat model that answers `/ask` questions (defaults to the Hermes connection) |
```

Add a section after the "Search index" section:

```markdown
## Ask your library

`/ask` is a chat that answers questions over your collection — grounded in record
summaries **and your notes** — and links each answer to its sources. Retrieval
uses the same FTS5 index as `/api/search`; answers come from a chat model
configured via `ATLAS_CHAT_*` (defaulting to your Hermes connection, so it works
with no extra config). It is **ungated** (answering is cheap relative to
collection) and multi-turn (history lives in your browser). After saving a note,
the index refreshes so your note becomes searchable.
```

- [ ] **Step 3: Update ARCHITECTURE**

In `docs/ARCHITECTURE.md`, update the status line test count, add the `aishelf.site.ask` and `aishelf.site.llm` rows to the `aishelf.site` component table:

```markdown
| `ask.py` | RAG core for `/ask` (pure): `retrieve` (FTS5 hits + each item's note), `build_messages` (grounded system prompt: numbered sources, `[n]` citations, no-source guard), `source_refs`, `latest_user_question`. |
| `llm.py` | Chat-model connection for answering (`ATLAS_CHAT_*`, defaulting to Hermes) + robust `stream_completion` (reuses `hermes.sse`). |
```

Add to the Routes table (after `/api/search`):

```markdown
| `GET /ask` | Ask-your-library chat page (ungated; per-browser history). |
| `POST /ask/chat` | SSE: retrieve over `atlas.db` (summaries + notes), stream a grounded answer, plus a `{sources}` event for the linked Sources panel. **Ungated.** |
```

Add a key-flow bullet after the "DB search" flow:

```markdown
- **Ask:** `POST /ask/chat` retrieves the top-K items for the latest question
  (FTS5 over summaries + notes), builds a grounded prompt (numbered sources,
  citation + no-hallucination rules), streams the answer from the `ATLAS_CHAT_*`
  model, and emits a `{sources}` event the page renders as links. Saving a note
  re-syncs the index so notes are searchable.
```

- [ ] **Step 4: Update CLAUDE.md**

In `CLAUDE.md`, add to the `aishelf/site/` module list: `ask.py` (RAG core) and `llm.py` (chat-model client). Add an env var bullet under Config:

```markdown
- `ATLAS_CHAT_BASE_URL` / `ATLAS_CHAT_API_KEY` / `ATLAS_CHAT_MODEL` — the chat
  model that answers `/ask` questions (each defaults to the matching `HERMES_*`).
```

- [ ] **Step 5: Rebuild the local DB for the new FTS column**

The `note` column is new; existing DBs need a rebuild to gain it.

Run: `python -m aishelf.db sync --rebuild`
Expected: prints `synced: +<n> ...` with no error.

- [ ] **Step 6: Final full test sweep**

Run: `pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/ARCHITECTURE.md CLAUDE.md
git commit -m "docs: document /ask, ATLAS_CHAT_* config, and the FTS rebuild step

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** chat-model config (Task 2), summaries + notes grounding (Tasks 1, 3), notes folded into FTS / Approach A (Task 1), multi-turn (route forwards full history, Task 4), ungated (Task 4), FTS5 retriever (Task 3), no-hallucination guard (Task 3 prompt + test), sources panel (Task 5), TDD with mocked LLM (all tasks). All covered.
- **Type consistency:** `Source` fields are identical across `ask.py`, its tests, and `source_refs`. `retrieve(db_path, question, *, k)`, `build_messages(messages, sources)`, `latest_user_question(messages)`, `source_refs(sources)`, and `llm.stream_completion(messages)` are referenced with the same signatures in app.py and tests.
- **Decoupling note:** the note→index refresh lives in the `/notes` route (which already has the DB deps), not in `notes.py`, keeping that pure I/O module dependency-free — same pattern as `collect_chat` (not `hermes.py`) owning the post-collection sync.
- **Rebuild gotcha:** `CREATE VIRTUAL TABLE IF NOT EXISTS` won't add the `note` column to an existing `items_fts`; deployment/local must run `python -m aishelf.db sync --rebuild` once (Task 6 Step 5). Test DBs are fresh, so unit tests are unaffected.

# AI 笔记草稿 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 「✨ AI 起草」button to the note editor that streams an AI-drafted note skeleton into the textarea for the user to edit and save.

**Architecture:** A new pure leaf module `aishelf/site/notedraft.py` (`build_messages` only, mirrors `collide.py`/`path.py`/`mirror.py`). One streaming route `POST /notes/{id}/draft` reuses existing app helpers (`items.safe_id`, `_items`, `_note_for`, `_item_dict`, `llm.stream_completion`). The editor button streams SSE deltas into the textarea; the user owns the save (existing `POST /notes/{id}`). No persistence change, no new config/deps.

**Tech Stack:** Python 3, FastAPI, Jinja2, pytest + FastAPI TestClient.

---

### Task 1: `notedraft.py` — pure `build_messages`

**Files:**
- Create: `src/aishelf/site/notedraft.py`
- Test: `tests/unit/test_site_note_draft.py`

- [ ] **Step 1: Write the failing test** (create `tests/unit/test_site_note_draft.py`):

```python
from aishelf.site import notedraft


_ITEM = {
    "title": "测试时计算扩展",
    "summary": "讨论推理阶段增加算力如何提升模型表现。",
    "keywords": ["推理", "scaling", "评测"],
    "author": "Karpathy",
    "type": "video",
}


def test_build_messages_shape_and_sections():
    msgs = notedraft.build_messages(_ITEM)
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    for tag in ["要点", "为什么值得记", "待探索"]:
        assert tag in system
    assert "Markdown" in system or "markdown" in system
    # user message grounds the model in the item
    assert "测试时计算扩展" in user
    assert "推理" in user            # a keyword
    assert "Karpathy" in user


def test_build_messages_includes_existing_note_and_no_repeat():
    msgs = notedraft.build_messages(_ITEM, "我已经记过：scaling 曲线在数学题上最明显。")
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "scaling 曲线在数学题上最明显" in user   # existing note passed through
    assert "重复" in system                          # instruction not to repeat


def test_build_messages_empty_note_omits_existing_section():
    msgs = notedraft.build_messages(_ITEM, "")
    user = msgs[1]["content"]
    assert "已有笔记" not in user      # no existing-note block when empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_site_note_draft.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aishelf.site.notedraft'`.

- [ ] **Step 3: Create `src/aishelf/site/notedraft.py`:**

```python
"""AI note-draft prompt builder (pure), mirroring collide.py / path.py / mirror.py.

Given an item's metadata (and any existing note), build the chat messages that
ask the model to draft a short Markdown note *skeleton* — 要点 / 为什么值得记 /
待探索 — for the user to edit and save. The route does the item lookup and
streaming; this module only phrases the prompt. Reuses ATLAS_CHAT_* via the site
llm client; no new config, no persistence.
"""

from __future__ import annotations


def build_messages(item: dict, existing_note: str = "") -> list[dict]:
    """System + user messages for drafting a note. `item` is the dict shape from
    app._item_dict (title/summary/keywords/author/type). When `existing_note` is
    non-empty it is shown so the draft complements rather than repeats it."""
    system = (
        "你是一个帮“我”做读书笔记的助手。我会给你一条 AI 领域内容的标题、摘要和关键词"
        "（注意：你只看得到摘要级别的信息，不是全文）。请据此起一份简洁的笔记骨架，"
        "供我之后补充。输出恰好三个 Markdown 小节，纯 Markdown，不要额外开场白或总结：\n"
        "## 要点\n（3-5 条要点，从摘要/关键词提炼，用无序列表）\n"
        "## 为什么值得记\n（1-2 句，这条内容对我可能的价值或独特角度）\n"
        "## 待探索\n（2-3 个这条内容引出但没回答的问题，用无序列表）\n"
        "具体、克制，不要空话套话。如果我已经写了笔记，只在已有内容之外补充，不要重复。"
    )
    kw = "、".join(item.get("keywords") or [])
    lines = [
        f"标题：{item.get('title', '')}",
        f"类型：{item.get('type', '')}",
        f"作者：{item.get('author', '')}",
        f"摘要：{item.get('summary', '')}",
    ]
    if kw:
        lines.append(f"关键词：{kw}")
    user = "\n".join(lines)
    if existing_note.strip():
        user += f"\n\n我已有笔记（请勿重复其内容）：\n{existing_note.strip()}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

Note the test asserts `"已有笔记" not in user` when the note is empty — the
existing-note block (which contains the literal "已有笔记") is only appended when
the note is non-empty, so that assertion holds. The non-empty test asserts
`"重复"` is in the **system** prompt ("不要重复" / "请勿重复") — present above.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_site_note_draft.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/notedraft.py tests/unit/test_site_note_draft.py
git commit -m "feat(site): notedraft.build_messages（AI 笔记草稿提示）"
```

---

### Task 2: Route `POST /notes/{id}/draft`

**Files:**
- Modify: `src/aishelf/site/app.py` (import `notedraft`; add route after the existing `POST /notes/{item_id}` route, ~line 588)
- Test: `tests/unit/test_site_note_draft.py`

- [ ] **Step 1: Write the failing route tests** — APPEND to `tests/unit/test_site_note_draft.py`:

```python
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    from aishelf.site import app as app_module
    monkeypatch.setattr(
        app_module.llm, "stream_completion",
        lambda messages: iter([app_module.hermes.sse({"delta": "## 要点\n- 草稿"}),
                               app_module.hermes.sse({"done": True})]),
    )
    return TestClient(app_module.app)


def test_note_draft_streams_for_known_id(client):
    r = client.post("/notes/youtube-aaa/draft")
    assert r.status_code == 200
    assert "草稿" in r.text          # canned delta streamed
    assert "done" in r.text


def test_note_draft_unknown_id_404(client):
    assert client.post("/notes/nope-zzz/draft").status_code == 404


def test_note_draft_unsafe_id_404(client):
    assert client.post("/notes/a..b/draft").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_site_note_draft.py -k draft -v`
Expected: FAIL — `POST /notes/youtube-aaa/draft` 404/405 (route not defined; note the path also overlaps nothing existing).

- [ ] **Step 3a: Add `notedraft` to the `aishelf.site` import block** in `src/aishelf/site/app.py` (alphabetical: insert `notedraft,` right after `notes,`).

- [ ] **Step 3b: Add the route immediately AFTER the existing `POST /notes/{item_id}` route** (the `save_note_route` function that ends with the `return {"ok": True, …}` line, ~line 588):

```python
@app.post("/notes/{item_id}/draft")
def note_draft(item_id: str):
    # Ungated: drafting is cheap (like /ask, /collide, /mirror), not the Hermes path.
    try:
        items.safe_id(item_id)
    except ValueError:
        raise HTTPException(status_code=404)
    it = next((x for x in _items() if x.id == item_id), None)
    if it is None:
        raise HTTPException(status_code=404)
    existing = _note_for(it)

    def _gen():
        yield from llm.stream_completion(notedraft.build_messages(_item_dict(it), existing))

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_note_draft.py -v`
Expected: PASS (6 tests). Then `python -m pytest -q` — whole suite green.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_note_draft.py
git commit -m "feat(site): POST /notes/{id}/draft（流式 AI 笔记草稿）"
```

---

### Task 3: Editor button + streaming JS

**Files:**
- Modify: `src/aishelf/site/templates/_note_editor.html` (add button + draft handler)
- Test: `tests/unit/test_site_note_draft.py`

The current `_note_editor.html` has a `.note-bar` containing `#note-save` and
`#note-status`, and a `<textarea id="note">`. We add a 「✨ AI 起草」button and a
handler that streams `/notes/{id}/draft` into the textarea. The detail pages
include this partial with `item` in context, so `{{ item.id }}` works (as it
already does for the save handler).

- [ ] **Step 1: Write the failing template test** — APPEND to `tests/unit/test_site_note_draft.py`:

```python
def test_editor_has_draft_button_and_endpoint(client):
    # the video detail page includes _note_editor.html
    r = client.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert "AI 起草" in r.text
    assert "/draft" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_site_note_draft.py -k editor -v`
Expected: FAIL — no 「AI 起草」/`/draft` in the page yet.

- [ ] **Step 3a: Add the button** to the `.note-bar` in `src/aishelf/site/templates/_note_editor.html`. Change:

```html
    <div class="note-bar">
      <button id="note-save" type="button" class="btn">保存笔记</button>
      <span id="note-status" class="note-status"></span>
    </div>
```

to:

```html
    <div class="note-bar">
      <button id="note-save" type="button" class="btn">保存笔记</button>
      <button id="note-draft" type="button" class="btn-link">✨ AI 起草</button>
      <span id="note-status" class="note-status"></span>
    </div>
```

- [ ] **Step 3b: Add the draft handler** inside the existing `<script>`'s IIFE, right
before the final `})();`. It reuses the same SSE delta-reader shape as
`mirror.html`/`collide.html` and streams into the textarea:

```javascript
  const draftBtn = document.getElementById("note-draft");
  let drafting = false;
  draftBtn.addEventListener("click", async () => {
    if (drafting) return;
    drafting = true; draftBtn.disabled = true;
    status.className = "note-status"; status.textContent = "正在起草…";
    const base = ta.value.trim() ? ta.value.replace(/\s+$/, "") + "\n\n" : "";
    let resp;
    try {
      resp = await fetch("/notes/{{ item.id }}/draft", { method: "POST" });
    } catch (e) {
      status.className = "note-status err"; status.textContent = "起草失败：" + e;
      drafting = false; draftBtn.disabled = false; return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "", acc = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let p; try { p = JSON.parse(line.slice(6)); } catch (e) { continue; }
          if (p.delta) { acc += p.delta; ta.value = base + acc; }
          else if (p.error) { status.className = "note-status err"; status.textContent = "⚠️ " + p.error; }
        }
      }
      if (acc && status.textContent === "正在起草…") { status.textContent = "草稿已生成，编辑后保存"; }
    } finally {
      drafting = false; draftBtn.disabled = false;
    }
  });
```

(`status`, `ta` are already defined at the top of the IIFE for the save handler.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_note_draft.py -v`
Expected: PASS (7 tests). Then `python -m pytest -q` — whole suite green.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/templates/_note_editor.html tests/unit/test_site_note_draft.py
git commit -m "feat(site): 笔记编辑器 AI 起草按钮（流式写入文本框）"
```

---

### Task 4: Docs — update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document `notedraft.py`** — in the `aishelf/site/` module bullet list,
add an entry near `notes.py`/`mirror.py`:

```
  `notedraft.py` (AI 笔记草稿: pure `build_messages` — from an item's
  title/summary/keywords (+ any existing note) phrases a 中文 Markdown note
  skeleton 要点/为什么值得记/待探索; mirrors collide.py/mirror.py's pure half;
  streamed by `POST /notes/{id}/draft`, no persistence/new config),
```

- [ ] **Step 2: Document the route** — near the notes prose (the paragraph describing
`POST /notes/{id}`), add:

```
`POST /notes/{id}/draft` streams an AI-drafted note skeleton (要点/为什么值得记/待探索)
from the item's metadata into the editor textarea via `llm.stream_completion`
(ungated like /ask; `safe_id` guard, unknown/unsafe id → 404); the user edits and
saves through `POST /notes/{id}` — drafts are never auto-saved.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: AI 笔记草稿（notedraft.py + POST /notes/{id}/draft）"
```

---

## Self-Review

**1. Spec coverage:**
- `notedraft.build_messages` (pure, 3 sections, existing-note handling) → Task 1 ✓
- Route `POST /notes/{id}/draft` (safe_id + lookup + stream, ungated, 404s) → Task 2 ✓
- Editor button + stream-into-textarea + no auto-save + error handling → Task 3 ✓
- Tests: build_messages (incl. existing-note + empty), route stream + 404s, editor template → Tasks 1–3 ✓
- CLAUDE.md → Task 4 ✓
- Out-of-scope honored (no auto-save, no history, no new config/deps/DB) — no task adds them ✓

**2. Placeholder scan:** No TBD/TODO; every code step has full code. The Task 1
note clarifies the two assertions that could be misread. ✓

**3. Type consistency:** `build_messages(item: dict, existing_note: str = "")`
identical in Tasks 1–2. Route calls `notedraft.build_messages(_item_dict(it), existing)`
— `_item_dict` returns exactly `{title, summary, keywords, author, type}` (verified
in app.py:126). JS posts to `/notes/{id}/draft` (matches route) and reads
`{"delta"}`/`{"error"}` events (matches `llm.stream_completion`). Button id
`note-draft`, reuses `status`/`ta` from the existing IIFE. ✓

# 抬杠 / 反方视角 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 「🔥 唱个反调」button on each item's detail page that streams an adversarial 中文 critique (软肋 / 反方 / 改判条件), challenging the user's note too when present.

**Architecture:** A new pure leaf module `aishelf/site/critique.py` (`build_messages` only, mirrors `notedraft.py`). One streaming route `POST /critique/{id}` reusing existing app helpers (`items.safe_id`, `_items`, `_note_for`, `_item_dict`, `llm.stream_completion`). A shared `_critique.html` partial (like `_note_editor.html`) included in both detail templates. No persistence, no new config/deps.

**Tech Stack:** Python 3, FastAPI, Jinja2, pytest + FastAPI TestClient.

---

### Task 1: `critique.py` — pure `build_messages`

**Files:**
- Create: `src/aishelf/site/critique.py`
- Test: `tests/unit/test_site_critique.py`

- [ ] **Step 1: Write the failing test** (create `tests/unit/test_site_critique.py`):

```python
from aishelf.site import critique


_ITEM = {
    "title": "测试时计算扩展",
    "summary": "讨论推理阶段增加算力如何提升模型表现。",
    "keywords": ["推理", "scaling", "评测"],
    "author": "Karpathy",
    "type": "video",
}


def test_build_messages_shape_and_sections():
    msgs = critique.build_messages(_ITEM)
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    for tag in ["最薄弱的地方", "反方会怎么说", "什么能说服你改主意"]:
        assert tag in system
    assert "steel" in system.lower() or "稻草人" in system   # steel-man, not strawman
    assert "Markdown" in system or "markdown" in system
    assert "测试时计算扩展" in user
    assert "推理" in user
    assert "Karpathy" in user


def test_build_messages_with_note_challenges_user_take():
    msgs = critique.build_messages(_ITEM, "我觉得 scaling 一定能解决推理。")
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "我觉得 scaling 一定能解决推理" in user   # note included
    assert "笔记" in system                          # told to challenge the user's take


def test_build_messages_empty_note_omits_note_block():
    msgs = critique.build_messages(_ITEM, "")
    assert "我的笔记" not in msgs[1]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_site_critique.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aishelf.site.critique'`.

- [ ] **Step 3: Create `src/aishelf/site/critique.py`:**

```python
"""Devil's-advocate critique prompt builder (pure), mirroring notedraft.py / collide.py.

Given an item's metadata (and any existing note), build the chat messages that ask
the model to argue *against* the content — its weakest point, the strongest opposing
case (steel-manned), and what would change the conclusion — and to push back on the
user's recorded take when there is one. The route does the lookup + streaming; this
module only phrases the prompt. Reuses ATLAS_CHAT_* via the site llm client; no new
config, no persistence.
"""

from __future__ import annotations


def build_messages(item: dict, note: str = "") -> list[dict]:
    """System + user messages for an adversarial critique. `item` is the dict shape
    from app._item_dict (title/summary/keywords/author/type). When `note` is
    non-empty it is shown and the model is told to challenge the user's take too."""
    system = (
        "你是一个爱抬杠但讲道理的批判者。我会给你一条 AI 领域内容的标题、摘要和关键词"
        "（你只看得到摘要级别的信息，不是全文）。请站在反方，对它唱个反调。"
        "输出恰好三段，每段以方括号小标题开头，每段不超过两句，要具体、有锋芒、对事不对人：\n"
        "【最薄弱的地方】它的论点或前提里最可能站不住、或被它忽略的一点。\n"
        "【反方会怎么说】把最强的反对立场讲出来——要 steel-man（替对方说出最有力的版本），"
        "不要稻草人。\n"
        "【什么能说服你改主意】一个具体的证据或观察，一旦出现就该改判。\n"
        "只输出这三段纯文本，不要使用 Markdown 语法（不要 # 或 * 等），不要额外开场白或总结。"
        "如果我附上了自己的笔记，也请顺带挑战我笔记里的看法。"
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
    if note.strip():
        user += f"\n\n我的笔记（也请一并挑战）：\n{note.strip()}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

Note the test assertions hold: system contains the three tags, `steel` (lowercase
in `system.lower()`) and `稻草人`, `Markdown`, `笔记`; the empty-note case omits the
literal "我的笔记" block.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_site_critique.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/critique.py tests/unit/test_site_critique.py
git commit -m "feat(site): critique.build_messages（反方视角提示）"
```

---

### Task 2: Route `POST /critique/{id}`

**Files:**
- Modify: `src/aishelf/site/app.py` (import `critique`; add route after the `POST /notes/{item_id}/draft` route)
- Test: `tests/unit/test_site_critique.py`

- [ ] **Step 1: Write the failing route tests** — APPEND to `tests/unit/test_site_critique.py`:

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
        lambda messages: iter([app_module.hermes.sse({"delta": "【最薄弱的地方】证据不足"}),
                               app_module.hermes.sse({"done": True})]),
    )
    return TestClient(app_module.app)


def test_critique_streams_for_known_id(client):
    r = client.post("/critique/youtube-aaa")
    assert r.status_code == 200
    assert "最薄弱的地方" in r.text
    assert "done" in r.text


def test_critique_unknown_id_404(client):
    assert client.post("/critique/nope-zzz").status_code == 404


def test_critique_unsafe_id_404(client):
    assert client.post("/critique/a..b").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_site_critique.py -k "streams or 404" -v`
Expected: FAIL — `POST /critique/youtube-aaa` 404/405 (route not defined).

- [ ] **Step 3a: Add `critique` to the `from aishelf.site import (...)` block** in app.py
(alphabetical: insert `critique,` right after `collect,`).

- [ ] **Step 3b: Add the route immediately AFTER the `POST /notes/{item_id}/draft` route**
(`note_draft`, which ends with `return StreamingResponse(_gen(), media_type="text/event-stream")`):

```python
@app.post("/critique/{item_id}")
def critique_route(item_id: str):
    # Ungated: critique is cheap (like /ask, /collide, /notes/{id}/draft), not the Hermes path.
    try:
        items.safe_id(item_id)
    except ValueError:
        raise HTTPException(status_code=404)
    it = next((x for x in _items() if x.id == item_id), None)
    if it is None:
        raise HTTPException(status_code=404)
    note = _note_for(it)

    def _gen():
        yield from llm.stream_completion(critique.build_messages(_item_dict(it), note))

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_critique.py -v`
Expected: PASS (6 tests). Then `python -m pytest -q` — whole suite green.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_critique.py
git commit -m "feat(site): POST /critique/{id}（流式反方视角）"
```

---

### Task 3: Frontend — `_critique.html` partial + includes + CSS

**Files:**
- Create: `src/aishelf/site/templates/_critique.html`
- Modify: `src/aishelf/site/templates/video_detail.html` (include partial)
- Modify: `src/aishelf/site/templates/blog_detail.html` (include partial)
- Modify: `src/aishelf/site/static/style.css` (small `.critique` block)
- Test: `tests/unit/test_site_critique.py`

- [ ] **Step 1: Write the failing template tests** — APPEND to `tests/unit/test_site_critique.py`:

```python
def test_video_detail_has_critique_button(client):
    r = client.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert "唱个反调" in r.text
    assert "/critique/" in r.text


def test_blog_detail_has_critique_button(client):
    r = client.get("/blogs/blog-ccc")
    assert r.status_code == 200
    assert "唱个反调" in r.text
    assert "/critique/" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_site_critique.py -k "detail_has" -v`
Expected: FAIL — no 「唱个反调」/`/critique/` in the pages.

- [ ] **Step 3a: Create `src/aishelf/site/templates/_critique.html`:**

```html
<section class="critique">
  <div class="critique-head">
    <h2>抬杠</h2>
    <button id="critique-btn" type="button" class="btn-link">🔥 唱个反调</button>
  </div>
  <div id="critique-result" class="critique-result" hidden></div>
</section>
<script>
(function () {
  const btn = document.getElementById("critique-btn");
  const out = document.getElementById("critique-result");
  let busy = false;
  btn.addEventListener("click", async () => {
    if (busy) return;
    busy = true; btn.disabled = true; out.hidden = false; out.className = "critique-result";
    out.textContent = "正在抬杠…";
    let resp;
    try {
      resp = await fetch("/critique/{{ item.id }}", { method: "POST" });
    } catch (e) { out.className = "critique-result err"; out.textContent = "⚠️ 无法连接服务"; busy = false; btn.disabled = false; return; }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "", acc = "", streaming = false;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let p; try { p = JSON.parse(line.slice(6)); } catch (e) { continue; }
          if (p.delta) { if (!streaming) { streaming = true; acc = ""; out.textContent = ""; } acc += p.delta; out.textContent = acc; }
          else if (p.error) { out.className = "critique-result err"; out.textContent = "⚠️ " + p.error; }
        }
      }
    } finally {
      busy = false; btn.disabled = false;
    }
  });
})();
</script>
```

- [ ] **Step 3b: Include the partial in `video_detail.html`** — change:

```html
  {% include "_keywords.html" %}
  {% include "_note_editor.html" %}
```

to:

```html
  {% include "_keywords.html" %}
  {% include "_critique.html" %}
  {% include "_note_editor.html" %}
```

- [ ] **Step 3c: Include the partial in `blog_detail.html`** — it has the same
`{% include "_keywords.html" %}` then `{% include "_note_editor.html" %}` pair near
the end; insert `{% include "_critique.html" %}` between them identically:

```html
  {% include "_keywords.html" %}
  {% include "_critique.html" %}
  {% include "_note_editor.html" %}
```

- [ ] **Step 3d: Append a `.critique` block to `static/style.css`:**

```css
/* 抬杠 / 反方视角 */
.critique { margin: 1.5rem 0; }
.critique-head { display: flex; align-items: center; gap: .75rem; }
.critique-head h2 { margin: 0; }
.critique-result {
  white-space: pre-wrap; line-height: 1.7; font-size: .95rem; margin-top: .8rem;
  padding: 1rem 1.2rem; border-radius: 12px;
  background: linear-gradient(135deg, rgba(255,107,157,.08), rgba(255,154,60,.06));
  border: 1px solid #3a2c31;
}
.critique-result.err { color: #ff9d9d; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_critique.py -v`
Expected: PASS (8 tests). Then `python -m pytest -q` — whole suite green.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/templates/_critique.html src/aishelf/site/templates/video_detail.html src/aishelf/site/templates/blog_detail.html src/aishelf/site/static/style.css tests/unit/test_site_critique.py
git commit -m "feat(site): 详情页抬杠组件（流式反方视角 + 注入两个详情页）"
```

---

### Task 4: Docs — update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document `critique.py`** — add to the `aishelf/site/` module bullet
list (near `notedraft.py`):

```
  `critique.py` (抬杠/反方视角: pure `build_messages` — from an item's metadata
  (+ any existing note) phrases a 中文 adversarial critique 最薄弱处/反方立场/改判条件,
  challenging the user's note too; mirrors notedraft.py's pure half; streamed by
  `POST /critique/{id}`, no persistence/new config),
```

- [ ] **Step 2: Document the route** — near the `/notes/{id}/draft` prose, add:

```
`POST /critique/{id}` streams an adversarial 中文 critique (最薄弱处/反方立场/改判条件)
of the item — and of the user's note when present — via `llm.stream_completion`,
shown in a 抬杠 panel on the detail page (ungated like /ask; `safe_id` guard,
unknown/unsafe id → 404); never persisted.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 抬杠/反方视角（critique.py + POST /critique/{id}）"
```

---

## Self-Review

**1. Spec coverage:**
- `critique.build_messages` (pure, 3 sections, steel-man, note handling) → Task 1 ✓
- Route `POST /critique/{id}` (safe_id + lookup + stream, ungated, 404s) → Task 2 ✓
- `_critique.html` partial + both detail includes + CSS, self-contained IIFE,
  textContent stream, error handling → Task 3 ✓
- Tests: build_messages (incl. note + empty), route stream + 404s, both detail pages → Tasks 1–3 ✓
- CLAUDE.md → Task 4 ✓
- Out-of-scope honored (no persistence/history, detail-page only, no new config/deps/DB) ✓

**2. Placeholder scan:** No TBD/TODO; every code step has full code. Task 1 note
clarifies the assertions. ✓

**3. Type consistency:** `build_messages(item: dict, note: str = "")` identical in
Tasks 1–2. Route calls `critique.build_messages(_item_dict(it), note)` — `_item_dict`
returns `{title,summary,keywords,author,type}`. JS posts to `/critique/{id}` (matches
route), reads `{"delta"}`/`{"error"}` (matches `llm.stream_completion`), sets
`textContent` only. Partial IIFE uses only local vars (`btn`/`out`/`busy`/`acc` —
distinct from `_note_editor.html`'s `ta`/`status`/`draftBtn`), so the two scripts on
the same page don't collide. Blog test uses `blog-ccc` (a collected blog present in
fixtures, reachable at `/blogs/blog-ccc`). ✓

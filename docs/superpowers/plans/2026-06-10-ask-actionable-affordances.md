# Ask Actionable Affordances Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two additive `/ask` affordances — content jump-cards (videos + blogs) on explicit "open/view" intent, and an empty→collect guide that sends the user to `/collect` (prefilled) when the DB lacks relevant content.

**Architecture:** Pure helpers in `aishelf.site.ask` (`nav_types`, `nav_candidates`, `nav_refs`, `is_low_confidence`) drive two new optional SSE events from `/ask/chat` (`{jump}`, `{collect}`) — low-confidence is evaluated first and suppresses jump. The frontend renders jump-cards / a collect-guide; `/collect` gains a `?q=` prefill. No extra LLM call, no new retrieval, grounded prompt unchanged.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, SSE, pytest (LLM mocked).

**Spec:** `docs/superpowers/specs/2026-06-10-ask-actionable-affordances-design.md`

---

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/aishelf/site/ask.py` | Modify | Add `nav_types`, `nav_candidates`, `nav_refs`, `NAV_MAX`; `is_low_confidence`, `RELEVANCE_FLOOR`; import `tokenize`. |
| `src/aishelf/site/app.py` | Modify | `/ask/chat` emits `{collect}` (precedence) or `{jump}`; `/collect` accepts `?q=` → `prefill`. |
| `src/aishelf/site/templates/ask.html` | Modify | `renderJump` + `renderCollect` + SSE branches. |
| `src/aishelf/site/templates/collect.html` | Modify | Prefill the composer textarea. |
| `src/aishelf/site/static/style.css` | Modify | `.jump-cards`/`.jump-card`/`.jump-btn` + `.collect-guide`/`.collect-btn`. |
| `tests/unit/test_site_ask.py` | Modify | Pure tests for the new `ask.py` helpers. |
| `tests/unit/test_site_ask_routes.py` | Modify | Route tests for `{jump}`/`{collect}` + precedence + template handlers. |
| `tests/unit/test_site_collect_routes.py` | Modify | `/collect?q=` prefill test. |
| `README.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md` | Modify | Document the affordances + SSE events + `?q=`. |

Run all tests with `pytest -q`.

---

## Task 1: `ask.py` navigation helpers

**Files:**
- Modify: `src/aishelf/site/ask.py`
- Test: `tests/unit/test_site_ask.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_site_ask.py` (it already imports `from aishelf.site import ask`, `from aishelf.site.ask import Source`, and defines `_src(i, note="")` building a `type="video"` Source):

```python
def _blog_src(i):
    return Source(id=f"b{i}", type="blog", title=f"博文{i}", author="作者乙",
                  platform="blog", summary=f"摘要{i}", keywords=["k"], note="")


def test_nav_types_video_intent():
    assert ask.nav_types("我要查看 Karpathy 的视频") == {"video"}
    assert ask.nav_types("播放这个视频") == {"video"}
    assert ask.nav_types("go to that video") == {"video"}


def test_nav_types_blog_intent():
    assert ask.nav_types("打开那篇 RAG 博客") == {"blog"}
    assert ask.nav_types("我要看这篇文章") == {"blog"}
    assert ask.nav_types("open that article") == {"blog"}


def test_nav_types_both():
    assert ask.nav_types("打开关于 agent 的视频和文章") == {"video", "blog"}


def test_nav_types_none_without_nav_verb():
    assert ask.nav_types("RAG 是什么") == set()
    assert ask.nav_types("总结一下 agent 相关视频") == set()
    assert ask.nav_types("这个视频讲了什么") == set()  # cue but no nav verb


def test_nav_candidates_filters_by_type_and_caps():
    sources = [_src(1), _blog_src(1), _src(2), _blog_src(2)]
    vids = ask.nav_candidates(sources, {"video"})
    assert [s.id for s in vids] == ["v1", "v2"]
    both = ask.nav_candidates(sources, {"video", "blog"})
    assert [s.id for s in both] == ["v1", "b1", "v2", "b2"]  # retrieval order preserved
    assert ask.nav_candidates(sources, set()) == []


def test_nav_candidates_caps_at_nav_max():
    many = [_src(i) for i in range(ask.NAV_MAX + 3)]
    assert len(ask.nav_candidates(many, {"video"})) == ask.NAV_MAX


def test_nav_refs_shape():
    assert ask.nav_refs([_src(1)]) == [
        {"id": "v1", "type": "video", "title": "标题1", "author": "作者甲", "platform": "youtube"},
    ]
```

NOTE: confirm `_src` sets `platform="youtube"`, `title=f"标题{i}"`, `author="作者甲"` (it does in the existing file); if the existing `_src` differs, adjust the `test_nav_refs_shape` expectation to match it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_site_ask.py -q`
Expected: the new tests FAIL (`AttributeError: module ... has no attribute 'nav_types'`).

- [ ] **Step 3: Implement the helpers** — in `src/aishelf/site/ask.py`, add the constants below `DEFAULT_K = 6`:

```python
NAV_MAX = 5

_NAV_VERBS = (
    "打开", "播放", "跳转", "前往", "带我去", "查看", "我要看", "我想看", "想看",
    "打开看", "open", "play", "watch", "go to",
)
_VIDEO_CUES = ("视频", "video")
_BLOG_CUES = ("博客", "文章", "帖子", "blog", "article", "post")
```

and add these functions (after `source_refs`):

```python
def nav_types(question: str) -> set[str]:
    """The {video, blog} subset the user explicitly asks to open/view.

    A modality is included iff (any nav verb) AND (that modality's cue) appears.
    Empty set means no navigation intent. ASCII matching is case-insensitive;
    CJK is unaffected by lower().
    """
    q = (question or "").lower()
    if not any(v in q for v in _NAV_VERBS):
        return set()
    types: set[str] = set()
    if any(c in q for c in _VIDEO_CUES):
        types.add("video")
    if any(c in q for c in _BLOG_CUES):
        types.add("blog")
    return types


def nav_candidates(sources: list[Source], types: set[str]) -> list[Source]:
    """Sources whose type is requested, in retrieval order, capped at NAV_MAX."""
    if not types:
        return []
    return [s for s in sources if s.type in types][:NAV_MAX]


def nav_refs(candidates: list[Source]) -> list[dict]:
    """Card payload for the client (links + label decided client-side by type)."""
    return [
        {"id": s.id, "type": s.type, "title": s.title, "author": s.author,
         "platform": s.platform}
        for s in candidates
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_site_ask.py -q`
Expected: PASS (all, including the new ones).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/ask.py tests/unit/test_site_ask.py
git commit -m "feat(ask): nav_types/nav_candidates/nav_refs for content jump-cards

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `ask.py` low-confidence detection

**Files:**
- Modify: `src/aishelf/site/ask.py`
- Test: `tests/unit/test_site_ask.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_site_ask.py`:

```python
def test_is_low_confidence_empty_sources():
    assert ask.is_low_confidence("任意问题", []) is True


def test_is_low_confidence_no_overlap():
    src = Source(id="v1", type="video", title="大语言模型与检索增强", author="作者甲",
                 platform="youtube", summary="一段摘要", keywords=[], note="")
    assert ask.is_low_confidence("量子计算最新进展", [src]) is True


def test_is_low_confidence_strong_overlap():
    src = Source(id="v1", type="video", title="大语言模型与检索增强", author="作者甲",
                 platform="youtube", summary="一段摘要", keywords=[], note="")
    assert ask.is_low_confidence("大语言模型", [src]) is False


def test_is_low_confidence_empty_question():
    src = Source(id="v1", type="video", title="标题", author="作者甲",
                 platform="youtube", summary="摘要", keywords=[], note="")
    assert ask.is_low_confidence("", [src]) is True  # no query tokens -> low confidence
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_site_ask.py -q`
Expected: the 4 new tests FAIL (`has no attribute 'is_low_confidence'`).

- [ ] **Step 3: Implement** — in `src/aishelf/site/ask.py`, extend the db import line:

```python
from aishelf.db import search as db_search
from aishelf.db import tokenize
```

add the constant near `NAV_MAX`:

```python
RELEVANCE_FLOOR = 0.15
```

and add the function (after `nav_refs`):

```python
def is_low_confidence(question: str, sources: list[Source]) -> bool:
    """True when the library has nothing relevant: no sources, or the top source
    shares fewer than RELEVANCE_FLOOR of the question's bigrams. Pure heuristic —
    empty retrieval is the primary signal, overlap is a conservative secondary
    catch for loose OR-mode matches."""
    if not sources:
        return True
    q_bigrams = set(tokenize.bigrams(question).split())
    if not q_bigrams:
        return True
    top = sources[0]
    text = " ".join([top.title, top.summary, " ".join(top.keywords), top.author, top.note])
    s_bigrams = set(tokenize.bigrams(text).split())
    overlap = len(q_bigrams & s_bigrams) / len(q_bigrams)
    return overlap < RELEVANCE_FLOOR
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_site_ask.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/ask.py tests/unit/test_site_ask.py
git commit -m "feat(ask): is_low_confidence (empty or low query-term overlap)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `/ask/chat` emits `{collect}` / `{jump}` with precedence

**Files:**
- Modify: `src/aishelf/site/app.py`
- Test: `tests/unit/test_site_ask_routes.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_site_ask_routes.py` (it has the `client` fixture seeding video `v1` "大语言模型与检索增强", the `_write` helper, `_chunk`, and `_FakeClient`; tests patch `llm.OpenAI`):

```python
def test_ask_chat_video_navigation_emits_jump(client, monkeypatch):
    from aishelf.site import llm
    monkeypatch.setattr(llm, "OpenAI", lambda **k: _FakeClient([_chunk("ok")]))
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "打开 大语言模型 视频"}]})
    assert r.status_code == 200
    assert '"jump"' in r.text
    assert '"type": "video"' in r.text
    assert "v1" in r.text
    assert '"collect"' not in r.text
    assert r.text.index('"jump"') < r.text.index('"delta"')  # before the answer


def test_ask_chat_blog_navigation_emits_jump(client, tmp_path, monkeypatch):
    _write(tmp_path, "blogs", "b1", "RAG 实践指南")  # unrelated to the video
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")
    from aishelf.site import llm
    monkeypatch.setattr(llm, "OpenAI", lambda **k: _FakeClient([_chunk("ok")]))
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "打开那篇 RAG 博客"}]})
    assert r.status_code == 200
    assert '"jump"' in r.text
    assert '"type": "blog"' in r.text
    assert "b1" in r.text


def test_ask_chat_ordinary_question_no_jump_no_collect(client, monkeypatch):
    from aishelf.site import llm
    monkeypatch.setattr(llm, "OpenAI", lambda **k: _FakeClient([_chunk("检索增强是…")]))
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "什么是检索增强"}]})
    assert r.status_code == 200
    assert '"jump"' not in r.text
    assert '"collect"' not in r.text


def test_ask_chat_no_match_emits_collect(client, monkeypatch):
    from aishelf.site import llm
    monkeypatch.setattr(llm, "OpenAI", lambda **k: _FakeClient([_chunk("没有相关内容")]))
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "量子计算最新进展"}]})
    assert r.status_code == 200
    assert '"collect"' in r.text
    assert "量子计算最新进展" in r.text          # the question is carried for prefill
    assert '"jump"' not in r.text
    assert r.text.index('"collect"') < r.text.index('"delta"')


def test_ask_chat_low_confidence_takes_precedence_over_jump(client, monkeypatch):
    # nav intent (打开...视频) but no matching content -> collect, NOT jump
    from aishelf.site import llm
    monkeypatch.setattr(llm, "OpenAI", lambda **k: _FakeClient([_chunk("ok")]))
    r = client.post("/ask/chat", json={"messages": [{"role": "user", "content": "打开关于量子计算的视频"}]})
    assert r.status_code == 200
    assert '"collect"' in r.text
    assert '"jump"' not in r.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_site_ask_routes.py -q`
Expected: the 5 new tests FAIL (no `{jump}`/`{collect}` events emitted yet).

- [ ] **Step 3: Implement** — in `src/aishelf/site/app.py`, replace the `ask_chat` route's `_gen` generator (currently emits only `{sources}` then the stream) with:

```python
    def _gen():
        # Emit the sources first so the client can render the panel immediately.
        yield hermes.sse({"sources": ask.source_refs(sources)})
        # Low confidence (empty / loose match) takes precedence: guide to collect
        # and suppress jump-cards. Otherwise, surface navigation jump-cards.
        if ask.is_low_confidence(question, sources):
            yield hermes.sse({"collect": {"q": question}})
        else:
            candidates = ask.nav_candidates(sources, ask.nav_types(question))
            if candidates:
                yield hermes.sse({"jump": ask.nav_refs(candidates)})
        yield from llm.stream_completion(payload)
```

(Leave the rest of `ask_chat` — the 400 guard, `question`/`sources`/`payload` computation, and `StreamingResponse(...)` — unchanged.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_site_ask_routes.py -q`
Expected: PASS (existing + 5 new). Then `pytest -q` to confirm no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_ask_routes.py
git commit -m "feat(ask): /ask/chat emits {collect} or {jump} (collect takes precedence)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `/collect?q=` prefill

**Files:**
- Modify: `src/aishelf/site/app.py`
- Modify: `src/aishelf/site/templates/collect.html`
- Test: `tests/unit/test_site_collect_routes.py`

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_site_collect_routes.py` (it has a `client` fixture and the `/collect` page is ungated):

```python
def test_collect_page_prefills_q(client):
    r = client.get("/collect", params={"q": "量子计算 视频"})
    assert r.status_code == 200
    assert "量子计算 视频" in r.text  # pre-filled into the composer textarea


def test_collect_page_no_q_is_blank(client):
    r = client.get("/collect")
    assert r.status_code == 200
    # composer renders with no prefilled text
    assert 'id="chatinput" rows="1" placeholder="输入采集需求，Enter 发送，Shift+Enter 换行…"></textarea>' in r.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_site_collect_routes.py -q`
Expected: `test_collect_page_prefills_q` FAILS (`q` not rendered).

- [ ] **Step 3: Implement the route** — in `src/aishelf/site/app.py`, change `collect_page` to accept `q` and pass `prefill`:

```python
@app.get("/collect", response_class=HTMLResponse)
def collect_page(request: Request, q: str = ""):
    return templates.TemplateResponse(
        request,
        "collect.html",
        {
            "schedules": schedules.load_schedules(),
            "last_run": schedule_state.load_state(get_data_dir()),
            "prefill": q,
        },
    )
```

- [ ] **Step 4: Implement the template** — in `src/aishelf/site/templates/collect.html`, change the composer textarea (currently `...换行…"></textarea>`) to render the prefill (autoescaped):

```html
      <textarea id="chatinput" rows="1" placeholder="输入采集需求，Enter 发送，Shift+Enter 换行…">{{ prefill | default('') }}</textarea>
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_site_collect_routes.py -q`
Expected: PASS. Note: `test_collect_page_no_q_is_blank` confirms the empty case renders `></textarea>` with nothing between the tags (Jinja `default('')` yields empty).

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/collect.html tests/unit/test_site_collect_routes.py
git commit -m "feat(site): /collect?q= prefills the collection composer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `ask.html` jump-cards + collect-guide rendering

**Files:**
- Modify: `src/aishelf/site/templates/ask.html`
- Modify: `src/aishelf/site/static/style.css`
- Test: `tests/unit/test_site_ask_routes.py`

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_site_ask_routes.py`:

```python
def test_ask_page_has_jump_and_collect_handlers(client):
    r = client.get("/ask")
    assert r.status_code == 200
    assert "renderJump" in r.text
    assert "renderCollect" in r.text
    assert "打开视频" in r.text
    assert "打开文章" in r.text
    assert "去 Hermes 采集" in r.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_site_ask_routes.py::test_ask_page_has_jump_and_collect_handlers -q`
Expected: FAIL (handlers/labels not present).

- [ ] **Step 3: Add the render functions** — in `src/aishelf/site/templates/ask.html`, immediately AFTER the existing `renderSources` function (which ends with the `(afterEl.parentElement || afterEl).insertAdjacentElement("afterend", box);` line and its closing `}`), insert:

```javascript

// Render content jump-cards (videos/blogs) beneath the answer.
function renderJump(afterEl, jump) {
  if (!jump || !jump.length) return;
  const box = document.createElement("div");
  box.className = "jump-cards";
  const label = document.createElement("div");
  label.className = "jump-label";
  label.textContent = "你想打开的内容";
  box.appendChild(label);
  jump.forEach((s) => {
    const card = document.createElement("div");
    card.className = "jump-card";
    const meta = document.createElement("span");
    meta.className = "jump-meta";
    meta.textContent = s.title + " — " + s.author + " · " + s.platform;
    const a = document.createElement("a");
    a.className = "jump-btn";
    a.href = (s.type === "video" ? "/videos/" : "/blogs/") + encodeURIComponent(s.id);
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = s.type === "video" ? "打开视频" : "打开文章";
    card.append(meta, a);
    box.appendChild(card);
  });
  (afterEl.parentElement || afterEl).insertAdjacentElement("afterend", box);
}

// When the library has nothing relevant, guide the user to collect it.
function renderCollect(afterEl, payload) {
  const box = document.createElement("div");
  box.className = "collect-guide";
  const text = document.createElement("span");
  text.className = "collect-text";
  text.textContent = "本地内容库暂时没有相关内容，去 Hermes 采集？";
  const a = document.createElement("a");
  a.className = "collect-btn";
  a.href = "/collect?q=" + encodeURIComponent((payload && payload.q) || "");
  a.textContent = "去 Hermes 采集";
  box.append(text, a);
  (afterEl.parentElement || afterEl).insertAdjacentElement("afterend", box);
}
```

- [ ] **Step 4: Wire the SSE branches** — in `src/aishelf/site/templates/ask.html`, in the SSE event loop the first branch is `if (payload.sources) { renderSources(assistantEl, payload.sources); } else if (payload.delta) {`. Insert two branches between `sources` and `delta`:

```javascript
      if (payload.sources) {
        renderSources(assistantEl, payload.sources);
      } else if (payload.jump) {
        renderJump(assistantEl, payload.jump);
      } else if (payload.collect) {
        renderCollect(assistantEl, payload.collect);
      } else if (payload.delta) {
```

(Only the two `else if` branches are added; the surrounding `sources`/`delta`/`error`/`done` handling is unchanged.)

- [ ] **Step 5: Add styles** — append to `src/aishelf/site/static/style.css`:

```css
/* Ask: content jump-cards + empty->collect guide */
.jump-cards { margin: 6px 0 14px 52px; display: flex; flex-direction: column; gap: 6px; }
.jump-label, .collect-text { font-size: 12px; color: #9aa5b1; }
.jump-card { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 13px; }
.collect-guide { margin: 6px 0 14px 52px; display: flex; align-items: center; gap: 10px; }
.jump-btn, .collect-btn { font-size: 13px; color: #fff; background: #0a84ff; padding: 4px 10px; border-radius: 6px; text-decoration: none; white-space: nowrap; }
.jump-btn:hover, .collect-btn:hover { opacity: .9; }
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/unit/test_site_ask_routes.py -q`
Expected: PASS (including `test_ask_page_has_jump_and_collect_handlers`). Then `pytest -q` to confirm the full suite is green.

- [ ] **Step 7: Commit**

```bash
git add src/aishelf/site/templates/ask.html src/aishelf/site/static/style.css tests/unit/test_site_ask_routes.py
git commit -m "feat(ask): render jump-cards and the empty->collect guide

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Docs + full sweep

**Files:**
- Modify: `README.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md`

- [ ] **Step 1: Baseline** — run `pytest -q`; confirm 0 failures. If anything fails, STOP and report.

- [ ] **Step 2: README** — in the "## Ask your library" section, append a paragraph:

```markdown
The answer surfaces two next-action affordances when relevant: if you explicitly
ask to open a video or blog (e.g. "打开那个 RAG 视频"), matching items appear as
**jump-cards** linking to their detail pages; if the library has nothing relevant
to your question, a **「去 Hermes 采集」** guide links to `/collect` with your
question pre-filled (`/collect?q=...`) so you can collect it in one step.
```

- [ ] **Step 3: ARCHITECTURE** — in `docs/ARCHITECTURE.md`:

(a) Update the `ask.py` row in the `aishelf.site` component table to mention the new helpers — append to that row's text:

```markdown
Also `nav_types` / `nav_candidates` / `nav_refs` (content jump-cards on explicit open/view intent) and `is_low_confidence` (empty/low-overlap → collect guide).
```

(b) In the Routes table, update the `POST /ask/chat` row to note the new events, and the `GET /collect` row to note `?q=`:

```markdown
| `POST /ask/chat` | SSE: `{sources}`, optional `{jump}` (open-intent jump-cards) or `{collect}` (empty→collect guide; takes precedence), then the streamed answer. **Ungated.** |
| `GET /collect` | Hermes chat page + 「定时采集」section; `?q=` pre-fills the collection composer. |
```

(c) After the "Ask:" key-flow bullet, append a sentence:

```markdown
  When the turn reads as an explicit open/view request the answer also carries
  `{jump}` cards to detail pages; when nothing relevant is found it carries a
  `{collect}` guide to `/collect?q=<question>` (low-confidence is checked first
  and suppresses jump-cards).
```

- [ ] **Step 4: CLAUDE.md** — in the `aishelf/site/` module list, extend the `ask.py` description:

```markdown
  `ask.py` (RAG core for `/ask`: `retrieve`, `build_messages`, `source_refs`,
  plus `nav_types`/`nav_candidates`/`nav_refs` for jump-cards and
  `is_low_confidence` for the empty→collect guide),
```

- [ ] **Step 5: Final sweep** — run `pytest -q`; confirm all green.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/ARCHITECTURE.md CLAUDE.md
git commit -m "docs: document /ask jump-cards, empty->collect guide, and /collect?q=

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** jump-cards videos+blogs (Task 1 + 5), low-confidence trigger empty+overlap (Task 2), precedence collect-over-jump (Task 3), `/collect?q=` prefill (Task 4), SSE contract `{sources}/{jump}/{collect}` (Task 3 + 5), tests incl. precedence + prefill (all tasks). Covered.
- **Type consistency:** `nav_types(question) -> set[str]`; `nav_candidates(sources, types)`; `nav_refs(candidates) -> [{id,type,title,author,platform}]`; `is_low_confidence(question, sources) -> bool`; `RELEVANCE_FLOOR`/`NAV_MAX` constants — all referenced identically in `app.py` and tests. `{collect}` payload is `{"q": question}`; frontend reads `payload.collect.q`.
- **No prompt change:** `build_messages` / `_RULES` untouched; the answer still streams unchanged. The affordances are pure additive SSE events + DOM.
- **No DB/schema change:** unlike the prior feature, nothing here alters `atlas.db`, so no `--rebuild` is needed.
- **Frontend insertion:** jump/collect boxes insert after `assistantEl.parentElement` (the `.msg` row), matching the `renderSources` fix so they render *below* the answer, not beside it.

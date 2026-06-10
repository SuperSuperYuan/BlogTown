# Ask content-navigation jump-cards — Design

**Date:** 2026-06-10
**Status:** Approved, ready for implementation plan
**Package:** `aishelf` (product: Atlas)
**Builds on:** [`2026-06-09-ask-your-library-design.md`](2026-06-09-ask-your-library-design.md)

## 1. Summary

On the `/ask` page, when the user's message reads as an explicit "open / view a
specific item" request (e.g. "我要查看 Karpathy 的那个 LLM 视频", "打开那篇关于
RAG 的博客"), render **content jump-cards** beneath the answer — each card shows
the item's title / author / platform with a prominent button that navigates to
its detail page (videos → `/videos/{id}` 「打开视频」, blogs → `/blogs/{id}`
「打开文章」). The assistant still answers normally; the cards are an **additive
UI layer** over the existing `/ask/chat` flow.

Both modalities are covered: the cards reflect the modality the user names —
"视频" surfaces videos, "博客 / 文章" surfaces blogs, mentioning both surfaces
both. This reuses the items already retrieved for the turn (no extra LLM call, no
new retrieval) plus a pure keyword-heuristic intent check — consistent with the
existing pure, testable `ask.py` core.

## 2. Goals / non-goals

**Goals**
- When the user explicitly asks to open/view a video or a blog/article, surface
  the matching item(s) as jump-cards with a clear button to the detail page, so
  the user can pick (filter) and jump.
- Cover **both** modalities — videos and blogs — routing by what the user names.
- Fire **only** on explicit navigation intent — ordinary Q&A turns (including
  "这个视频讲了什么") must NOT show jump-cards.
- Keep the existing answer + grounding Sources panel exactly as they are.
- Zero added cost: no extra model call, reuse the turn's retrieved sources.

**Non-goals (YAGNI for this iteration)**
- LLM-based intent classification (keyword heuristic is enough for a personal tool).
- Item thumbnails / cover images on the cards (text-only, matching the Sources
  panel style; avoids threading new fields through `SearchHit`/`Source`).
- Jumping to a timestamp within a video.
- Changing the grounded prompt or the streamed answer.

## 3. Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| UX on nav intent | **Normal answer + candidate jump-cards** | Keeps the conversational answer; cards are additive. |
| Intent detection | **Keyword heuristic (pure function)** | Cheap, deterministic, unit-testable; fits `ask.py`'s pure-core style. |
| Modality coverage | **Videos and blogs**, routed by the user's wording | The user wants blog detail-page jumps covered alongside videos. |
| Candidate source | **Reuse the turn's retrieved sources, filtered to the named type(s)** | No new retrieval / LLM call; the FTS hits already rank by relevance. |
| Card content | **Text-only (title / author / platform) + type-appropriate button** | Matches existing Sources styling; no new data fields. |

## 4. Architecture

### 4.1 Flow (additive to the existing `/ask/chat`)

```
question + history
   │
   ▼
 retrieve(db_path, question)            ── unchanged (FTS5 OR-mode, summaries+notes)
   │ sources (mixed video/blog)
   ├─────────────► build_messages(...) ──► llm.stream_completion(...)  (answer, unchanged)
   │
   ▼
 nav_types(question)                    ── pure keyword heuristic → subset of {"video","blog"}
   │ non-empty (= navigation intent)?      empty ─► (emit nothing extra)
   ▼
 nav_candidates(sources, types)          (matching type(s), capped at NAV_MAX)
   │ non-empty?  no ─► (emit nothing)
   ▼
 SSE event {"jump": nav_refs(candidates)}   (emitted before the answer deltas)
   │
   ▼
 page renders a 「你想打开的内容」 card list; each card jumps by its own type
```

### 4.2 New / changed units

| Unit | Responsibility |
|---|---|
| `aishelf.site.ask` (extend) | `nav_types(question: str) -> set[str]` — the subset of `{"video","blog"}` the question expresses an explicit open/view intent for (empty set = no navigation intent). `nav_candidates(sources: list[Source], types: set[str]) -> list[Source]` — the sources whose `type` is in `types`, preserving retrieval (bm25) order, capped at `NAV_MAX` (= 5). `nav_refs(candidates) -> list[dict]` — `{id, type, title, author, platform}` per card. All pure. |
| `aishelf.site.app` (`/ask/chat`) | After computing `sources`, compute `types = ask.nav_types(question)`; if `types` and `ask.nav_candidates(sources, types)` is non-empty, the SSE generator yields `hermes.sse({"jump": ask.nav_refs(candidates)})` **before** the answer deltas (after/with the existing `{sources}` event). Otherwise no `{jump}` event. The grounded prompt and answer streaming are unchanged. |
| `aishelf.site.templates/ask.html` | A `renderJump(afterEl, jump)` JS handler (parallel to `renderSources`): on a `{jump}` SSE event, render a `.jump-cards` block under the answer row — a heading 「你想打开的内容」 and one `.jump-card` per item showing `标题 — 作者 · 平台` and a button `<a class="jump-btn">`. The button href and label are type-driven: video → `/videos/{id}` 「打开视频」, blog → `/blogs/{id}` 「打开文章」; `target="_blank" rel="noopener"`. Empty/absent `{jump}` → nothing rendered. |
| `static/style.css` | Styles for `.jump-cards`, `.jump-card`, `.jump-btn`, using the existing palette tokens (`#9aa5b1` muted, `#0a84ff` accent). |

### 4.3 Intent heuristic

`nav_types(question)` returns which modalities the user explicitly wants to open
or view. It matches on a curated set of open/go style trigger phrases — NOT the
bare verb 看 (which appears in ordinary Q&A like "看看这个视频讲了啥"):

- Open/go verbs: `打开`, `播放`, `跳转`, `前往`, `带我去`, `查看`, `我要看`,
  `我想看`, `想看`, `打开看`, plus ASCII `open` / `play` / `watch` / `go to`.
- Modality cues:
  - **video** ← the question contains `视频` (or ASCII `video`).
  - **blog** ← the question contains `博客`, `文章`, `帖子` (or ASCII `blog` /
    `article` / `post`).

The rule: a modality is included iff **(any nav verb) AND (that modality's cue)**
is present. So "我要查看那个 RAG 视频" → `{"video"}`; "打开那篇 transformer 博客"
→ `{"blog"}`; "打开关于 agent 的视频和文章" → `{"video","blog"}`; "RAG 是什么" →
`{}` (no nav verb); "这个视频讲了什么" → `{}` (cue but no nav verb). The phrase
lists live in `ask.py` as module constants and are the unit-tested core. False
positives are low-harm (an extra helpful card list); false negatives just fall
back to the normal answer + Sources panel.

## 5. SSE contract

`/ask/chat` event types become: `{"sources": [...]}` (existing), optional
`{"jump": [...]}` (new), `{"delta": "..."}`, `{"error": "..."}`, `{"done": true}`.
Each `jump` item: `{"id", "type", "title", "author", "platform"}`. The `{jump}`
event is emitted at most once per turn, before any `{delta}`.

## 6. Edge cases

- Non-navigation turn → no `{jump}` event; page renders answer + Sources only.
- Navigation intent but no item of the named type among the retrieved sources →
  no `{jump}` event (no empty card block).
- Mixed intent (`{"video","blog"}`) → candidates of both types, interleaved in
  retrieval (bm25) order, capped to `NAV_MAX` total.
- More than `NAV_MAX` candidates → capped to the top `NAV_MAX` by retrieval rank.
- XSS: card title/author/platform rendered via `textContent`; the href is
  `/videos/` or `/blogs/` (by `type === "video"`) + `encodeURIComponent(id)` —
  same safety as the Sources panel.

## 7. Testing (TDD; LLM mocked)

- `nav_types` (pure):
  - video intent → `{"video"}` ("我要查看 Karpathy 的视频", "打开那个 transformer
    视频", "播放这个视频", "go to that video").
  - blog intent → `{"blog"}` ("打开那篇 RAG 博客", "我要看这篇文章", "open that
    article").
  - both → `{"video","blog"}` ("打开关于 agent 的视频和文章").
  - none → `set()` ("RAG 是什么", "总结一下 agent 相关视频", "这个视频讲了什么").
- `nav_candidates` (pure): filters mixed sources to the requested type(s),
  preserves order, caps at `NAV_MAX`.
- `nav_refs` (pure): shape `{id, type, title, author, platform}`.
- `/ask/chat` route (mocked LLM): a video-navigation message with a video in the
  corpus emits a `{jump}` containing that video's id with `type == "video"` (and
  it precedes `{delta}`); a blog-navigation message emits a `{jump}` with the
  blog's id and `type == "blog"`; an ordinary question emits NO `{jump}`; a
  video-navigation message whose corpus has only blogs emits no `{jump}`.
- `ask.html` render: contains `renderJump`, 「打开视频」, and 「打开文章」.

## 8. Out of scope (restated)

LLM-based intent, item thumbnails, timestamps, and any change to the grounded
prompt / answer. These can be revisited later if the heuristic proves too blunt
or richer cards are wanted.

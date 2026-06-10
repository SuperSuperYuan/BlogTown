# Ask video-navigation jump-cards — Design

**Date:** 2026-06-10
**Status:** Approved, ready for implementation plan
**Package:** `aishelf` (product: Atlas)
**Builds on:** [`2026-06-09-ask-your-library-design.md`](2026-06-09-ask-your-library-design.md)

## 1. Summary

On the `/ask` page, when the user's message reads as an explicit "open / view a
specific video" request (e.g. "我要查看 Karpathy 的那个 LLM 视频", "打开那个
transformer 视频"), render **video jump-cards** beneath the answer — each card
shows the video's title / author / platform with a prominent **「打开视频」**
button that navigates to its detail page (`/videos/{id}`). The assistant still
answers normally; the cards are an **additive UI layer** over the existing
`/ask/chat` flow.

This reuses the items already retrieved for the turn (no extra LLM call, no new
retrieval) and a pure keyword-heuristic intent check — both consistent with the
existing pure, testable `ask.py` core.

## 2. Goals / non-goals

**Goals**
- When the user explicitly asks to open/view a video, surface the matching
  video(s) as jump-cards with a clear button to the detail page, so the user can
  pick (filter) and jump.
- Fire **only** on explicit navigation intent — ordinary Q&A turns (including
  "这个视频讲了什么") must NOT show jump-cards.
- Keep the existing answer + grounding Sources panel exactly as they are.
- Zero added cost: no extra model call, reuse the turn's retrieved sources.

**Non-goals (YAGNI for this iteration)**
- LLM-based intent classification (keyword heuristic is enough for a personal tool).
- Blog jump-cards (the request was specifically about videos).
- Video thumbnails on the cards (text-only, matching the Sources panel style;
  avoids threading new fields through `SearchHit`/`Source`).
- Jumping to a timestamp within a video.
- Changing the grounded prompt or the streamed answer.

## 3. Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| UX on nav intent | **Normal answer + candidate jump-cards** | Keeps the conversational answer; cards are additive. |
| Intent detection | **Keyword heuristic (pure function)** | Cheap, deterministic, unit-testable; fits `ask.py`'s pure-core style. |
| Candidate scope | **Videos only** | The request was specifically "查看 xxx 视频". |
| Candidate source | **Reuse the turn's retrieved sources, filtered to videos** | No new retrieval / LLM call; the FTS hits already rank by relevance. |
| Card content | **Text-only (title / author / platform) + button** | Matches existing Sources styling; no new data fields. |

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
 is_video_navigation(question)?         ── pure keyword heuristic
   │ yes                                   no ─► (emit nothing extra)
   ▼
 nav_candidates(sources) → videos        (capped at NAV_MAX)
   │ non-empty?  no ─► (emit nothing)
   ▼
 SSE event {"jump": nav_refs(candidates)}   (emitted before the answer deltas)
   │
   ▼
 page renders a 「🎬 你想打开的视频」 card list, each with a 「打开视频」 link button
```

### 4.2 New / changed units

| Unit | Responsibility |
|---|---|
| `aishelf.site.ask` (extend) | `is_video_navigation(question: str) -> bool` — True iff the question contains an explicit video-navigation phrase (curated trigger list). `nav_candidates(sources: list[Source]) -> list[Source]` — the `type == "video"` sources, capped at `NAV_MAX` (= 5). `nav_refs(candidates) -> list[dict]` — `{id, title, author, platform}` per card. All pure. |
| `aishelf.site.app` (`/ask/chat`) | After computing `sources`, if `ask.is_video_navigation(question)` and `nav_candidates(sources)` is non-empty, the SSE generator yields `hermes.sse({"jump": ask.nav_refs(candidates)})` **before** the answer deltas (after/with the existing `{sources}` event). Otherwise no `{jump}` event. The grounded prompt and answer streaming are unchanged. |
| `aishelf.site.templates/ask.html` | A `renderJump(afterEl, jump)` JS handler (parallel to `renderSources`): on a `{jump}` SSE event, render a `.jump-cards` block under the answer row — a heading 「🎬 你想打开的视频」 and one `.jump-card` per item showing `标题 — 作者 · 平台` and an `<a class="jump-btn">打开视频</a>` to `/videos/{id}` (`target="_blank" rel="noopener"`). Empty/absent `{jump}` → nothing rendered. |
| `static/style.css` | Styles for `.jump-cards`, `.jump-card`, `.jump-btn`, using the existing palette tokens (`#9aa5b1` muted, `#0a84ff` accent). |

### 4.3 Intent heuristic

`is_video_navigation(question)` returns True when the question contains an
explicit open/go style request for a video. It matches on a curated set of
trigger phrases rather than the bare verb 看 (which appears in ordinary Q&A like
"看看这个视频讲了啥"). The trigger set (case-insensitive; substring match on the
raw question):

- Open/go verbs: `打开`, `播放`, `跳转`, `前往`, `带我去`, `查看`, `我要看`,
  `我想看`, `想看`, `打开看`, plus ASCII `open` / `play` / `watch` / `go to`.
- Scoped by a video cue: the question must ALSO contain `视频` (or ASCII
  `video`). This keeps "打开收藏页" or generic asks from triggering, and matches
  the user's wording "查看 xxx **视频**".

So the rule is: **(any nav verb) AND (视频 / video)**. The exact phrase list
lives in `ask.py` as a module constant and is the unit-tested core. False
positives are low-harm (an extra helpful card list); false negatives just fall
back to the normal answer + Sources panel.

## 5. SSE contract

`/ask/chat` event types become: `{"sources": [...]}` (existing), optional
`{"jump": [...]}` (new), `{"delta": "..."}`, `{"error": "..."}`, `{"done": true}`.
Each `jump` item: `{"id", "title", "author", "platform"}`. The `{jump}` event is
emitted at most once per turn, before any `{delta}`.

## 6. Edge cases

- Non-navigation turn → no `{jump}` event; page renders answer + Sources only.
- Navigation intent but no video among the retrieved sources → no `{jump}` event
  (no empty card block).
- More than `NAV_MAX` video candidates → capped to the top `NAV_MAX` by retrieval
  rank (bm25 order from `retrieve`).
- XSS: card title/author/platform rendered via `textContent`; the href is
  `/videos/` + `encodeURIComponent(id)` — same safety as the Sources panel.

## 7. Testing (TDD; LLM mocked)

- `is_video_navigation` (pure): explicit nav phrases → True ("我要查看 Karpathy
  的视频", "打开那个 transformer 视频", "播放这个视频", "go to that video");
  ordinary Q&A → False ("RAG 是什么", "总结一下 agent 相关视频", "这个视频讲了
  什么" — has 视频 but no nav verb).
- `nav_candidates` (pure): filters mixed sources to videos, caps at `NAV_MAX`.
- `nav_refs` (pure): shape `{id, title, author, platform}`.
- `/ask/chat` route (mocked LLM): a navigation-intent message with a video in the
  corpus emits a `{jump}` event containing that video's id (and it precedes
  `{delta}`); an ordinary question emits NO `{jump}` event; a nav-intent message
  whose corpus has only blogs emits no `{jump}`.
- `ask.html` render: contains `renderJump` and the 「打开视频」 label.

## 8. Out of scope (restated)

LLM-based intent, blog jump-cards, thumbnails, timestamps, and any change to the
grounded prompt / answer. These can be revisited later if the heuristic proves
too blunt or richer cards are wanted.

# Ask actionable affordances — Design

**Date:** 2026-06-10
**Status:** Approved, ready for implementation plan
**Package:** `aishelf` (product: Atlas)
**Builds on:** [`2026-06-09-ask-your-library-design.md`](2026-06-09-ask-your-library-design.md)

## 1. Summary

Two additive UI affordances on the `/ask` page that turn an answer into *next
actions*, both reusing what `/ask/chat` already computes (no extra LLM call, no
new retrieval), driven by pure helpers in `ask.py`:

1. **Content jump-cards** — when the user explicitly asks to open/view a specific
   item (e.g. "我要查看 Karpathy 的那个 LLM 视频", "打开那篇关于 RAG 的博客"),
   render jump-cards beneath the answer that navigate to the item's detail page
   (videos → `/videos/{id}` 「打开视频」, blogs → `/blogs/{id}` 「打开文章」). Both
   modalities, routed by what the user names.
2. **Empty → collect guide** — when the local DB has no relevant content for the
   request, render a guide beneath the answer offering to jump to the Hermes
   `/collect` page with the user's question pre-filled, so they can collect it.

The assistant still answers normally in both cases; the grounding Sources panel
is unchanged. These are additive SSE events + frontend handlers layered over the
existing flow.

## 2. Goals / non-goals

**Goals**
- On an explicit open/view request, surface matching video(s) **and** blog(s) as
  jump-cards with a clear button to the detail page (user picks / filters).
- When the DB lacks relevant content, guide the user to `/collect` with their
  question pre-filled — they always confirm by clicking (no auto-collection).
- Fire each affordance only on its condition; ordinary Q&A turns (e.g. "这个视频
  讲了什么") show neither.
- Keep the existing answer + grounding Sources panel exactly as they are.
- Zero added cost: no extra model call, reuse the turn's retrieved sources.

**Non-goals (YAGNI for this iteration)**
- LLM-based intent / relevance judgment (keyword + overlap heuristics suffice).
- Item thumbnails / cover images on cards (text-only, matching the Sources panel).
- Auto-triggering collection (the user always clicks through to `/collect`).
- Jumping to a timestamp; tuning bm25 scores.
- Changing the grounded prompt or the streamed answer.

## 3. Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| UX on nav intent | **Normal answer + candidate jump-cards** | Keeps the conversational answer; cards are additive. |
| Intent detection | **Keyword heuristic (pure function)** | Cheap, deterministic, unit-testable; fits `ask.py`'s pure-core style. |
| Modality coverage | **Videos and blogs**, routed by the user's wording | Blog detail-page jumps alongside videos. |
| Candidate source | **Reuse the turn's retrieved sources, filtered to the named type(s)** | No new retrieval / LLM call; FTS hits already rank by relevance. |
| "No relevant content" trigger | **Empty retrieval OR low query-term overlap** | Catches both zero hits and loose OR-mode matches. |
| Low-relevance metric | **Query-bigram overlap ratio vs. the top hit, tunable floor** | Interpretable, pure, no magic bm25 number; contained in `ask.py`. |
| Collect hand-off | **Jump to `/collect?q=<question>` (prefilled), user confirms** | One-step collection; no auto-spend of the Hermes budget. |
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
   ├─ is_low_confidence(question, sources)            (pure: empty OR low overlap)
   │     │ true  → SSE {"collect": {"q": question}}   (takes precedence; skip jump)
   │     │ false → nav_types(question) → {video?,blog?} (pure keyword heuristic)
   │     │            │ non-empty → nav_candidates(sources, types) (capped NAV_MAX)
   │     │            │     │ non-empty → SSE {"jump": nav_refs(...)}
   │
   ▼  (the jump OR collect event emitted before the answer deltas)
 page renders: jump-cards (per type) OR a 「去 Hermes 采集」 guide
```

`{jump}` and `{collect}` are **mutually exclusive by precedence**: low confidence
is evaluated first and emits `{collect}` (suppressing `{jump}`); only a confident
turn with nav intent emits `{jump}`. This avoids showing weak jump-cards next to
a "nothing relevant" guide.

### 4.2 New / changed units

| Unit | Responsibility |
|---|---|
| `aishelf.site.ask` — navigation | `nav_types(question: str) -> set[str]` — subset of `{"video","blog"}` the question expresses an explicit open/view intent for (empty = no nav intent). `nav_candidates(sources, types) -> list[Source]` — sources whose `type` is in `types`, in retrieval order, capped at `NAV_MAX` (= 5). `nav_refs(candidates) -> list[dict]` — `{id, type, title, author, platform}`. Pure. |
| `aishelf.site.ask` — confidence | `is_low_confidence(question: str, sources: list[Source]) -> bool` — `True` if `sources` is empty, OR the top source's query-bigram overlap ratio `< RELEVANCE_FLOOR` (module constant, default `0.15`). Overlap = `|Q ∩ S| / |Q|` where `Q = set(tokenize.bigrams(question).split())` and `S` = bigrams of the top source's `title + summary + keywords + author + note`; empty `Q` → `True`. Pure. |
| `aishelf.site.app` (`/ask/chat`) | After computing `sources`, evaluate confidence FIRST: if `is_low_confidence(question, sources)` → yield `hermes.sse({"collect": {"q": question}})` (and emit no `{jump}`). Otherwise, if `nav_types(question)` and `nav_candidates` non-empty → yield `hermes.sse({"jump": nav_refs(...)})`. The chosen event is emitted before the answer deltas, after the existing `{sources}` event. Grounded prompt + answer streaming unchanged. |
| `aishelf.site.app` (`/collect`) | `collect_page` accepts a `q: str = ""` query param and passes it to the template as `prefill`, so `/collect?q=...` pre-populates the collection composer. |
| `aishelf.site.templates/ask.html` | `renderJump(afterEl, jump)` — render a `.jump-cards` block (heading 「你想打开的内容」) with one `.jump-card` per item (`标题 — 作者 · 平台` + `<a class="jump-btn">`), href/label by type (video → `/videos/{id}` 「打开视频」, blog → `/blogs/{id}` 「打开文章」, `target="_blank" rel="noopener"`). `renderCollect(afterEl, payload)` — render a `.collect-guide` box ("本地暂时没有相关内容，去 Hermes 采集？") with a 「去 Hermes 采集」 `<a class="collect-btn">` linking to `/collect?q=<encodeURIComponent(payload.q)>` (same tab). Empty/absent events render nothing. |
| `aishelf.site.templates/collect.html` | Pre-fill the composer textarea with the `prefill` value (autoescaped) when present. |
| `static/style.css` | Styles for `.jump-cards`/`.jump-card`/`.jump-btn` and `.collect-guide`/`.collect-btn`, using existing palette tokens (`#9aa5b1` muted, `#0a84ff` accent). |

### 4.3 Navigation intent heuristic

`nav_types(question)` matches on a curated set of open/go trigger phrases — NOT
the bare verb 看 (which appears in ordinary Q&A like "看看这个视频讲了啥"):

- Open/go verbs: `打开`, `播放`, `跳转`, `前往`, `带我去`, `查看`, `我要看`,
  `我想看`, `想看`, `打开看`, plus ASCII `open` / `play` / `watch` / `go to`.
- Modality cues: **video** ← `视频` / `video`; **blog** ← `博客` / `文章` /
  `帖子` / `blog` / `article` / `post`.

A modality is included iff **(any nav verb) AND (that modality's cue)** is
present. Examples: "我要查看那个 RAG 视频" → `{"video"}`; "打开那篇 transformer
博客" → `{"blog"}`; "打开关于 agent 的视频和文章" → `{"video","blog"}`; "RAG 是
什么" → `{}`; "这个视频讲了什么" → `{}` (cue but no nav verb). The phrase lists
live in `ask.py` as module constants and are the unit-tested core.

### 4.4 Low-confidence heuristic

`RELEVANCE_FLOOR = 0.15` (module constant, tunable). Empty retrieval is the
primary signal; the overlap ratio is a conservative secondary catch for loose
OR-mode matches. It is a heuristic: a false positive only shows an extra
"去采集?" guide (low harm); a false negative falls back to the LLM's existing
no-source verbal suggestion. Filler words in the question lower the ratio
uniformly, which is why the floor is deliberately low.

## 5. SSE contract

`/ask/chat` events: `{"sources": [...]}` (existing), optional `{"jump": [...]}`
(each `{id, type, title, author, platform}`), optional `{"collect": {"q": "..."}}`,
then `{"delta": "..."}` / `{"error": "..."}` / `{"done": true}`. The `{jump}` and
`{collect}` events are each emitted at most once per turn, before any `{delta}`.

## 6. Edge cases

- Ordinary turn (matches found, no nav intent) → neither `{jump}` nor `{collect}`.
- Nav intent but no item of the named type among retrieved sources → no `{jump}`.
- Mixed nav intent (`{"video","blog"}`) → both types, retrieval (bm25) order,
  capped to `NAV_MAX` total.
- Low confidence → `{collect}` with the verbatim question for prefill (URL-encoded
  in the link); `{jump}` is suppressed even if the turn also reads as nav intent.
- `/collect?q=` with an empty/missing `q` → composer renders empty (unchanged).
- XSS: card/guide text via `textContent`; jump href is `/videos/` or `/blogs/`
  (by `type === "video"`) + `encodeURIComponent(id)`; collect href is
  `/collect?q=` + `encodeURIComponent(q)`; the server-side `prefill` is rendered
  through Jinja autoescaping.

## 7. Testing (TDD; LLM mocked)

**Navigation (pure):**
- `nav_types`: video intent → `{"video"}` ("我要查看 Karpathy 的视频", "播放这个
  视频", "go to that video"); blog intent → `{"blog"}` ("打开那篇 RAG 博客", "我要
  看这篇文章", "open that article"); both → `{"video","blog"}`; none → `set()`
  ("RAG 是什么", "总结一下 agent 相关视频", "这个视频讲了什么").
- `nav_candidates`: filters mixed sources to requested type(s), preserves order,
  caps at `NAV_MAX`. `nav_refs`: shape `{id, type, title, author, platform}`.

**Confidence (pure):**
- `is_low_confidence`: empty sources → `True`; a source whose text shares none of
  the query's bigrams → `True`; a strongly-overlapping query/source → `False`.

**Routes (mocked LLM):**
- video-navigation message with a matching video → `{jump}` containing that id
  with `type=="video"`, preceding `{delta}`; blog-navigation → `{jump}` with the
  blog id and `type=="blog"`; ordinary matched question → no `{jump}`,
  no `{collect}`.
- a question with no DB match → `{collect}` with `q` equal to the question,
  preceding `{delta}`; a well-matched question → no `{collect}`.
- precedence: a low-confidence message that ALSO reads as nav intent (e.g. "打开
  关于量子计算的视频" with no quantum content) emits `{collect}` and NO `{jump}`.
- `GET /collect?q=区块链` → response body pre-fills `区块链` in the composer.

**Template:** `ask.html` contains `renderJump`, `renderCollect`, 「打开视频」,
「打开文章」, and 「去 Hermes 采集」.

## 8. Out of scope (restated)

LLM-based intent/relevance, item thumbnails, timestamps, auto-collection, bm25
tuning, and any change to the grounded prompt / answer.

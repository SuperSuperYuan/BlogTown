# 「灵感碰撞」(Idea Collision) — Design

**Date:** 2026-06-17
**Status:** Approved, ready for implementation plan
**Roadmap position:** Idea **B** of the A→B→C evolution (A 一句话钩子 ✅ shipped → **B 灵感碰撞** → C 今日速读). B is the "好玩" centerpiece.

## Problem

Atlas collects and queries AI content well, and (after A) every item is legible at
a glance. But the library is still a list of *separate* things. The fun, generative
move for someone working in AI is to **collide two items and see what idea falls
out** — the connection you'd never have drawn yourself. This is the playful
centerpiece of the evolution, and it must stay 简洁: reuse the LLM + embeddings +
graph machinery already present, add no persistence.

## Goal

A `/collide` page that serves a **surprising pair** of library items and an
LLM-written **three-part synthesis** of how they relate. "Random-first" with
control: reshuffle the pair, or **lock one side** and reshuffle only the other.
On-demand only — nothing is saved.

## Locked design decisions

- **Interaction:** random-first. On load, a surprising pair + its synthesis appear.
  「再来一对」reshuffles both; a 🔒 lock toggle on either card fixes that item and
  reshuffles only the other.
- **Pairing strategy:** "中相似带 + 跨类型/作者优先" — candidate pairs are those whose
  embedding cosine falls in `[0.30, GRAPH_SIM_FLOOR)` = `[0.30, 0.50)` (related, but
  below the graph's edge threshold so they are *not* an obvious/already-drawn link),
  and among those, **prefer cross-type (video×blog) and cross-author** pairs for
  maximum "意外" feel.
- **Output:** three plain-text sections — `【共同的暗线】` / `【关键张力】` /
  `【碰撞出的新点子】` — each 1–2 sentences, punchy, no fluff. Plain text (not
  markdown), rendered with `white-space: pre-wrap`, mirroring `/ask` which streams
  into `textContent` with no client markdown library.
- **No persistence; no new config** (reuses `ATLAS_CHAT_*` for chat and
  `ATLAS_EMBED_*` for embeddings).

## Architecture

A single streaming endpoint mirrors `/ask/chat`: it **picks the pair, emits it,
then streams the synthesis** in one request (just as `/ask` emits `sources` and
then streams the answer). The `/collide` page is a focused single-purpose UI — no
chat history, avatars, or persistence — much simpler than `ask.html`.

### Routes (`src/aishelf/site/app.py`)

- `GET /collide` → `templates.TemplateResponse("collide.html", {})` (page shell).
- `POST /collide/chat`, JSON body `{a_id?: str, b_id?: str, lock_id?: str}`:
  1. `space = collide.load_pair_space(default_db_path(get_data_dir()))`.
  2. Resolve the pair from `items = _items()` + `space`:
     - both `a_id` and `b_id` present → use them (deep-link / explicit).
     - else `lock_id` present → fix A = `lock_id`, pick a surprising B for it.
     - else → pick a fully surprising pair.
  3. If a pair cannot be formed (`<2` items) → emit `sse({"error": "先去采集一些内容再来碰撞"})` then `sse({"done": True})` and return.
  4. `yield sse({"pair": {"a": ref(a), "b": ref(b)}})` where `ref` = `{id, type, title, author}` (client renders the two cards immediately).
  5. `yield from llm.stream_completion(collide.build_messages(a, b))`.

  Returned as `StreamingResponse(_gen(), media_type="text/event-stream")`. Ungated
  (synthesis is cheap, like `/ask`; not the costly Hermes path).

### New module `src/aishelf/site/collide.py`

Pure functions + one thin DB loader; mirrors how `graph.py` separates impure
`_load_groups` from pure `neighbors`.

- `load_pair_space(db_path) -> tuple[list[str], "np.ndarray", dict]` — one query
  `SELECT id, embedding, embedding_dim, type, author FROM items WHERE embedding IS NOT NULL`;
  group by `embedding_dim`, take the largest group → `ids`, `(N, dim)` matrix, and
  `meta = {id: {"type": ..., "author": ...}}`. Returns `([], empty, {})` when no
  embeddings. Tolerant of a missing/old DB (returns empties) so the route can fall
  back to a random pair without crashing.

- `pick_pair(ids, matrix, meta, *, lock_id=None, rng, lo=0.30, hi=graph.GRAPH_SIM_FLOOR) -> tuple[str, str] | None`
  **(pure)** — the heart of the feature:
  - Compute candidate index pairs `(i, j)` with `lo <= cosine(i, j) < hi`.
  - **Score** each candidate: `+1` if cross-type, `+1` if cross-author (so a
    different-type *and* different-author pair scores 2). Group candidates by score.
  - Pick uniformly at random (via `rng`) from the **highest-scoring tier** that is
    non-empty (preferring score 2, then 1, then 0).
  - With `lock_id`: restrict candidates to those containing `lock_id` before
    scoring; return `(lock_id, other)`.
  - Returns `None` when no band candidates exist (caller falls back).
  - Deterministic given a seeded `rng` (so tests are stable).

- `random_pair(item_ids, *, lock_id=None, rng) -> tuple[str, str] | None` **(pure)**
  — fallback: two distinct ids at random (honoring `lock_id`); `None` if `<2` ids.

- `build_messages(a, b) -> list[dict]` **(pure)** — `a`/`b` are item dicts (or the
  contract items' relevant fields: `title`, `summary`, `keywords`, `author`,
  `type`). System prompt (Chinese) instructs exactly three plain-text sections,
  each on its own block, each 1–2 sentences, concrete and provocative, no empty
  talk:
  - `【共同的暗线】` — the non-obvious shared thread.
  - `【关键张力】` — where they pull against / disagree with each other.
  - `【碰撞出的新点子】` — a fresh idea sparked by combining them.
  User message lists both items (title + summary + keywords). Plain text only — no
  markdown syntax — because the client renders `textContent`.

### Pair resolution helper (route-level)

The route turns resolved ids back into the full contract items (from `_items()`)
to build messages and the card refs. A small private helper
`_resolve_pair(items, space, *, a_id, b_id, lock_id, rng)` in `app.py` ties
`pick_pair`/`random_pair` together and maps ids → items, returning the two item
objects or `None`. (Kept in `app.py` because it bridges files + DB + request, like
`_hooks_for`.)

### Client (`src/aishelf/site/templates/collide.html`)

Mirrors `/ask`'s streaming consumption: `fetch('/collide/chat', {method:'POST', body: JSON})`
→ `resp.body.getReader()` → `TextDecoder` → split on lines → for each `data: ` line
`JSON.parse` and handle `pair` / `delta` / `error` / `done`.

- On load: POST with `{}` → render the pair's two cards (title, author, type badge,
  linking to `/videos/{id}` or `/blogs/{id}`) and stream the synthesis into a
  `white-space: pre-wrap` result panel.
- Controls:
  - **「再来一对」** → POST `{}` (or `{lock_id}` if one card is locked).
  - **🔒 lock toggle** on each card → marks that id as locked; the next reshuffle
    sends `{lock_id: <that id>}`, fixing it and reshuffling the other. Only one side
    lockable at a time (locking one clears the other's lock).
- A typing/loading indicator while waiting for the first `delta` (reuse `/ask`'s
  pattern lightly; keep minimal).

### Navigation + styles

- `_topbar.html`: add a 「碰撞」link (consistent with the existing nav items / the
  topbar.css link styling).
- `style.css`: a small block for the two facing cards (e.g. a `.collide-pair`
  flex row with a central `✦`/`×` divider), the lock toggle, and the
  `.collide-result` pre-wrap panel. Reuse existing color tokens (`#0a84ff` accent,
  muted grays).

## Data flow

```
GET /collide → page shell
page JS POST /collide/chat {} 
  → load_pair_space(db) + _items()
  → pick_pair (mid-band, cross-type/author)  [fallback: random_pair]
  → emit {"pair": {a, b}}  → cards render
  → llm.stream_completion(build_messages(a,b)) → {"delta": …}* → {"done": true}
「再来一对」/ lock → POST again with optional {lock_id}
```

## Degradation & errors

- **No embeddings** (`ATLAS_EMBED_*` unset, or `<2` embedded): `load_pair_space`
  returns empties → `pick_pair` returns `None` → route uses `random_pair` over all
  item ids. The feature still works, just less "意外".
- **No chat model**: `llm.stream_completion` already emits an in-stream
  `{"error": …}` and stops — the page shows the error (same as `/ask`).
- **`<2` items total**: route emits the empty-state error message; the page shows
  "先去采集一些内容再来碰撞".
- All DB reads tolerate a missing/old DB (return empties), never crashing the page.

## Testing

(LLM/network always mocked, per repo convention.)

- **`pick_pair`** (pure, seeded `rng`): selects only in-band pairs; prefers
  cross-type and cross-author (score-2 tier chosen over score-1/0 when present);
  honors `lock_id` (result always contains it); returns `None` when no in-band
  pairs; stable under a fixed seed.
- **`random_pair`**: two distinct ids; honors `lock_id`; `None` when `<2`.
- **`build_messages`**: system prompt names all three sections; both items' titles
  and summaries appear in the payload; no markdown syntax requested.
- **`load_pair_space`**: returns largest-dim group with `meta`; empties for a DB
  with no embeddings / missing DB.
- **Route `POST /collide/chat`** (mock `llm.stream_completion` + a seeded space):
  emits a `pair` event before any `delta`; explicit `{a_id,b_id}` honored;
  `{lock_id}` keeps that id in the pair; `<2` items → error event, no crash.
- **`GET /collide`** → 200, shell renders (nav link present).

## Non-goals (YAGNI)

- No persistence / history of past collisions.
- No 碰撞 entry button on item detail pages (could come later; `?a=&b=` deep-link is
  *not* added now — the route accepts `a_id/b_id` for tests/future use but no UI
  links to it).
- No multi-item (3+) collisions.
- No new environment variable; no markdown rendering library on the client.
- Not surfaced on home/graph in this iteration.

## Files

- Create: `src/aishelf/site/collide.py`, `src/aishelf/site/templates/collide.html`.
- Modify: `src/aishelf/site/app.py` (two routes + `_resolve_pair`),
  `src/aishelf/site/templates/_topbar.html` (nav link),
  `src/aishelf/site/static/style.css` (collide styles).
- Tests: `tests/unit/test_collide.py`, `tests/unit/test_site_collide_routes.py`.

## Documentation touch-ups (on implementation)

- `CLAUDE.md`: add `aishelf/site/collide.py` (pair selection + `build_messages`),
  the `GET /collide` + `POST /collide/chat` routes, and a one-line feature note.

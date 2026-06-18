# 藏书镜 / 阅读画像 (collection-persona mirror) — Design

**Date:** 2026-06-18
**Status:** Approved (autonomous-iteration; author = approver, rationale logged inline)

## Why

The A→B→C roadmap (一句话钩子 / 灵感碰撞 / 今日速读) is shipped. Atlas already
turns a pile of items into a knowledge graph of **主题星系 (theme galaxies)** —
but that intelligence only lives inside `/graph`. Nothing in Atlas ever tells
*you* something surprising about **your own** collection.

「藏书镜」holds a mirror up to the reader, not the content. On demand, it
synthesizes the *whole* collection into a grounded, slightly cheeky 中文
**阅读人格 (reading persona)**: your dominant 主线, your recent 转向, a thin
盲区, a one-line persona, and one concrete next-step suggestion drawn **only
from your own collection**.

This is the same family as 灵感碰撞 / 今日速读 (content-surprise, not visual
gimmickry; no gamification, no recommendation engine reaching outside the
corpus) — which is exactly the taste the project is steered toward
(简洁 + 实用 + 好玩，拒绝花里胡哨; distill rather than decorate; reuse existing
infrastructure). **好玩** comes from the surprise of being read by your own
library; **实用** comes from the closing 盲区→补什么 takeaway.

## What it is

- A new page `GET /mirror` ("藏书镜") with one primary action: 「照一照」.
- `POST /mirror/chat` builds a structured **profile** of the collection from the
  derived DB, emits a compact fact strip (galaxies + counts) as the first SSE
  event, then **streams** a 中文 portrait via `llm.stream_completion`.
- On-demand, **no persistence, no caching** — exactly like `/collide` and
  `/graph/path`.

### The portrait (LLM output)

Plain text, no Markdown, exactly these bracketed sections (mirrors
collide/path prompt style):

```
【你的主线】     2-3 主导星系，每条 1-2 句：它们暴露了你在痴迷什么。
【最近的转向】   最近收藏相对整体偏向了什么（或"没有明显转向"）。1-2 句。
【一个盲区】     最薄的那个星系，1-2 句，略带锋芒。
【一句话人格】   一句俏皮的人格速写。
```

Followed by one final sentence: a concrete next-step suggestion **derived from
the collection itself** (extend a 主线 or fill the 盲区) — never an external
recommendation.

Decision: portrait is **clusters-based**. The galaxies are the centerpiece of
Atlas's intelligence; the mirror reflects them. This keeps **one code path**.
When there are no clusters (embeddings unconfigured, or DB not yet synced, or
empty corpus), the page shows a friendly empty state — the same graceful
degradation as `/collide` when there are <2 embeddings. (Rationale: a second
keyword-based code path would be decoration, not distillation — YAGNI.)

## Architecture — mirrors `collide.py` / `path.py`

New module `src/aishelf/site/mirror.py` with the established split: **one thin DB
loader + pure prompt builder**, no new subsystem, no new config (reuses
`ATLAS_CHAT_*` via `llm`, and the `clusters`/`items` tables already built at
sync time).

```
load_profile(db_path, *, recent_n=10) -> Profile | None
    Thin DB reader. Returns None when there are no named/unnamed clusters
    (i.e. no embeddings synced) or no items — caller shows the empty state.
    Tolerant of a missing/old DB (returns None, never raises) — same posture
    as db.search.hooks_for / collide.load_pair_space.

build_messages(profile: Profile) -> list[dict]   # pure
    System + user chat messages asking for the bracketed portrait above.
```

### Data shapes (pure dataclasses in `mirror.py`)

```python
@dataclass
class Galaxy:
    name: str          # cluster name; "" when unnamed (alias pipeline off)
    color: str         # clusters.color — for the fact-strip pills (matches /graph)
    size: int          # member count
    recent: int        # members within the recent-N window (for 转向)
    titles: list[str]  # up to 5 sample member titles (grounding for the LLM)

@dataclass
class Profile:
    galaxies: list[Galaxy]          # sorted by size desc
    total: int                      # items with a cluster
    videos: int                     # type counts over clustered items
    blogs: int
    top_authors: list[tuple[str, int]]   # up to 3 (author, count); blanks skipped
    span_days: int                  # earliest→latest collected_at, 0 if unknown
    recent_n: int
```

### `load_profile` logic (pure-ish SQL over the derived DB)

1. `connect` + `init_db` (tolerant; on `sqlite3.Error` → `None`).
2. Read `clusters` → `{id: (name, color)}`.
3. Read `items` rows that have `cluster IS NOT NULL`: `id, type, author,
   collected_at, title, cluster`.
4. If no clustered items → `None`.
5. Recent window: sort clustered items by `collected_at` desc (reuse the same
   tolerant ISO-parse key as `digest._collected_key`), take the first
   `recent_n`; count per cluster → `recent`.
6. Per cluster: `size`, `recent`, up to 5 `titles` (first by id order — no
   embedding math needed; representativeness already baked into membership).
7. `videos`/`blogs` from type counts; `top_authors` = 3 most common non-empty
   authors; `span_days` from min/max parseable `collected_at`.
8. Sort galaxies by `size` desc.

`collected_at` parsing is duplicated minimally; to avoid a cross-module import
cycle (`digest` is a leaf, `mirror` is a leaf), `mirror` gets its own small
`_collected_key` helper (a handful of lines, same logic). Decision: tiny
duplication over a new shared util — both modules stay leaves, matching how
`collide`/`path` each keep their own small helpers.

### Route wiring (`app.py`)

```python
@app.get("/mirror")  -> templates.TemplateResponse("mirror.html", {})
@app.post("/mirror/chat") -> StreamingResponse(_gen(), "text/event-stream")
```

`_gen()`:
- `profile = mirror.load_profile(default_db_path(get_data_dir()))`
- if `profile is None`: `yield hermes.sse({"error": "先采集一些内容并同步图谱，才能照镜子"})`
  then `{"done": True}`.
- else: `yield hermes.sse({"profile": _profile_payload(profile)})` (galaxies
  `[{name,color,size}]`, total, videos, blogs, span_days, top author), then
  `yield from llm.stream_completion(mirror.build_messages(profile))`.

Ungated (synthesis is cheap, like `/collide` and `/ask` — not the Hermes path).
A small `_profile_payload(profile)` helper in `app.py` (mirrors `_collide_ref`).

### Frontend (`templates/mirror.html`)

Mirrors `collide.html` structure and its SSE-reading JS almost verbatim:
- `<h2>藏书镜 <span class="hint">照一照你的收藏，看看你是谁</span></h2>`
- a 「照一照 ↻」 button (re-runnable — re-streams; LLM nondeterminism gives a
  fresh read each time, which is part of the fun).
- a fact strip `#facts` rendering galaxy pills (colored via `galaxy.color`, like
  the `/graph` legend) + a small `N 条 · M 视频 · K 博客 · 跨度 D 天` line.
- a `#result` area showing the streamed portrait.
- **All dynamic text escaped via the same `escapeHtml` helper** collide uses
  (galaxy names, authors). Pills get their color via an escaped/validated style.
  Runs once on load (`run()`), re-runs on button click; button disabled while
  busy. Reuses the exact `pair`-style SSE loop, swapping `pair`→`profile`.
- Add `<a href="/mirror">镜子</a>` to `_topbar.html` nav (after 碰撞).

### Styling

Add a small `.mirror` block to `static/style.css` (where `.collide` lives) reusing collide's visual
language (bracket-section emphasis, gradient accent like the digest card). No
new assets. Galaxy pills reuse the palette already on screen in `/graph`.

## Error handling

- No clusters / empty / missing-old DB → `load_profile` returns `None` →
  friendly empty-state error event (no crash).
- Chat model unconfigured/unreachable → `llm.stream_completion` already yields a
  `{"error": …}` event and `{"done": True}`; the page shows ⚠️ (same as
  `/collide`).
- All template output autoescaped; client-built HTML escaped via `escapeHtml`;
  pill colors come from the fixed `cluster.PALETTE` (validated `^#[0-9a-fA-F]{6}$`
  before use, else dropped) so a malformed color can't inject style.

## Testing (pytest, network mocked — see CLAUDE.md conventions)

Unit tests in `tests/unit/test_site_mirror.py`:

- **`build_messages` (pure):** returns system+user; user text contains galaxy
  names, sizes, sample titles, and the overall stats; system prompt demands the
  four bracketed sections + plain text (no Markdown). Deterministic — no LLM.
- **`load_profile`:** build a temp DB via `db.schema` + `sync` (or direct
  inserts) with ≥2 clusters; assert galaxies sorted by size desc, `recent`
  counts reflect the recent window, type counts, `top_authors`, `span_days`.
- **`load_profile` degradation:** missing DB file → `None`; DB with items but no
  clusters (embeddings off) → `None`; never raises.
- **Route `POST /mirror/chat`** (TestClient, `llm.stream_completion` monk
  eypatched to yield canned `delta` events): emits a `profile` event then the
  deltas; with an empty/clusterless DB emits the `error` event. `GET /mirror`
  returns 200 and contains 「藏书镜」.
- **Topbar:** a page contains the `/mirror` nav link.

## Out of scope (YAGNI)

- No persistence/caching of portraits. No history of past reads.
- No keyword-based fallback when clusters are absent (one code path).
- No per-galaxy drill-down page (the galaxies already live in `/graph`).
- No new config, no new dependency, no sync-time work (purely read-time).

## File touch list

- **new** `src/aishelf/site/mirror.py`
- **new** `src/aishelf/site/templates/mirror.html`
- **new** `tests/unit/test_site_mirror.py`
- **edit** `src/aishelf/site/app.py` (2 routes + `_profile_payload`; import `mirror`)
- **edit** `src/aishelf/site/templates/_topbar.html` (nav link)
- **edit** `src/aishelf/site/static/style.css` — small `.mirror` block
- **edit** `CLAUDE.md` (document `mirror.py` + the two routes)

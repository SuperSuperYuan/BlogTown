# 进阶路线 / 学习路径 (learning path) — Design

**Date:** 2026-06-18
**Status:** Approved (autonomous-iteration; author = approver, rationale logged inline)

## Why

Atlas can now **read** (一句话钩子, 今日速读), **synthesize** (灵感碰撞, 藏书镜),
and **assist-write** (AI 笔记草稿). It cannot **sequence**. The 主题星系 (theme
galaxies) already group the collection by topic — but a pile of same-topic items
is not a reading order. A newcomer (or future-you) staring at the 推理模型 galaxy
has no idea which to watch first.

「进阶路线」turns a chosen galaxy into an ordered **curriculum**: the LLM sequences
that galaxy's items 入门 → 进阶 → 纵深 and gives a one-line 「为什么这一步」for each
stop, with clickable links to the items. It is a new *capability* (sequencing),
not another prose synthesis — the output is a navigable ordered list over content
you already own.

Fits the taste (简洁 + 实用 + 好玩，拒绝花里胡哨; distill rather than decorate;
reuse clusters + the LLM client). **实用** = a real "where do I start / what next."
**好玩** = watching your own pile resolve into a guided path. Same on-demand,
no-persistence, no-new-config shape as `/collide` / `/mirror`. Distinct from the
graph's 语义路径 (a walk between two arbitrary stars) — this orders N items *within
one theme* by conceptual progression.

## What it is

- A new page `GET /learn` ("进阶路线") that **server-renders** the list of theme
  galaxies as clickable pills (name + size, colored like the `/graph` legend).
- `POST /learn/route` takes a `cluster_id`, loads that galaxy's items, and
  **streams** a 中文 ordered curriculum via `llm.stream_completion`.
- On-demand, **no persistence, no caching**. Ungated (cheap synthesis, like
  `/ask`/`/collide`/`/mirror`).

### The route output (LLM)

Plain text, no Markdown, honest that it sequences from summary-level info. Shape:

```
（一句开场：这条线整体在讲什么、怎么走）
1. <这一步看哪条> — 为什么放在这一步（1 句）
2. …
3. …
```

The frontend turns each `N.` item's referenced title into a link. Decision: to make
linking robust, the LLM is told to **start each step with the item's exact title**
(provided in the prompt) so the client can match titles → ids without the model
inventing an id syntax. Titles are matched client-side against the galaxy's item
list (which the page already has); unmatched lines render as plain text. (Rationale:
keeps the model's job purely linguistic; no brittle id round-tripping in the prompt.)

## Architecture — mirrors `collide.py` / `mirror.py`

New leaf module `src/aishelf/site/learn.py`: pure `build_messages` + one thin,
tolerant DB loader (mirrors the `collide.load_pair_space` / `mirror.load_profile`
split). No new config; reuses `ATLAS_CHAT_*` via `llm` and the `clusters`/`items`
tables built at sync time.

```python
load_galaxies(db_path) -> list[Galaxy]   # all galaxies, each WITH its items; [] on missing/old/empty DB
build_messages(galaxy_name: str, items: list[dict]) -> list[dict]   # pure
```

Single loader keeps one tested path: `GET /learn` renders the full list, and
`POST /learn/route` picks the one matching `cluster_id` from the same loader. (For
a small personal corpus, loading all galaxies' items once per request is cheap and
avoids a second loader/endpoint.)

### Data shapes (dataclasses in `learn.py`)

```python
@dataclass
class Item:
    id: str
    title: str
    summary: str
    type: str       # "video" | "blog"

@dataclass
class Galaxy:
    id: int
    name: str       # cluster name; "" when unnamed
    color: str      # clusters.color
    size: int
    items: list     # list[Item]; empty for list_galaxies (filled only by load_galaxy)
```

`load_galaxies` returns all galaxies sorted by size desc, each with its `items`
populated (id/title/summary/type for the clustered items), or `[]` when there are
no clustered items / the DB is missing. It wraps DB access in
`try/except sqlite3.Error` → `[]` (never raises), like `mirror.load_profile`.
`Galaxy.items` is always populated by this loader (the `items=[]`-for-chooser
note in the dataclass comment no longer applies — both call sites get items).

### `build_messages`

System prompt: a 中文 "课程设计者"; given a galaxy's items (title + summary),
output an ordered 入门→进阶→纵深 path; one line per step beginning with the item's
**exact title**, then ` — ` and a ≤1-sentence reason; a short opening line; plain
text, no Markdown; don't invent items outside the list; if only 1 item, say so
plainly. User message: the galaxy name + a numbered list of its items
(title + truncated summary).

### Route wiring (`app.py`)

```python
@app.get("/learn")  -> server-render learn.html with galaxies=list_galaxies(db)
@app.post("/learn/route") -> StreamingResponse over llm.stream_completion(build_messages(...))
```

`POST /learn/route` (Pydantic `_LearnRequest{cluster_id:int}`): `load_galaxies(db)`,
pick the galaxy whose `id == cluster_id`; if missing or `<1` items → emit
`{"error": "这个星系还没有内容"}` + `{"done": true}`; else emit
`{"galaxy": {id,name}}` (for a heading) then
`yield from llm.stream_completion(learn.build_messages(name, item_dicts))`. The
`GET /learn` route passes the galaxy list so the client can render pills and link
titles; to avoid a second request, the page embeds, per galaxy, its items'
`{id,title,type}` (summary stripped to keep it small) as a JSON script block
(server-rendered via `tojson`). `learn` added to the `aishelf.site` import block.

`llm.stream_completion` already yields `{"delta"}` + final `{"done": true}` and
converts an unconfigured/unreachable model into an `{"error"}` event — graceful
degradation with no extra code (same as `/mirror`).

### Frontend (`templates/learn.html`)

Mirrors `collide.html`/`mirror.html` JS. Server-rendered galaxy pills (`data-cid`,
colored via a validated style). The per-galaxy items map is embedded as
`{{ galaxies_json | tojson }}` in a `<script type="application/json">` block and
parsed once. Clicking a pill:
- highlights it, clears the result, POSTs `{cluster_id}` to `/learn/route`;
- reads the SSE stream with the same delta-reader loop; accumulates text;
- renders the accumulated text **line by line**: for each line, if it starts with
  (optional `N.` +) a known item title from that galaxy, wrap the title in an
  `<a href="/videos|blogs/{id}">`; otherwise render escaped text. All dynamic text
  escaped via the shared `escapeHtml`; links built from server-provided ids only
  (never from model output), so no injection.
- empty-state / `{"error"}` → show ⚠️ message.

Add `<a href="/learn">路线</a>` to `_topbar.html` nav (after 镜子).

### Styling

Add a small `.learn` block to `static/style.css` reusing the galaxy-pill visual
language already used by `/mirror` (`.mx-pill` style) + the streamed-result panel
look. No new assets.

## Error handling

- No clusters / empty / missing-old DB → `list_galaxies` returns `[]` → page shows a
  friendly empty state ("先采集内容并同步图谱后再来"); `POST /learn/route` with an
  unknown/empty cluster → `{"error"}` event. No crash.
- Chat model unconfigured/unreachable → `llm.stream_completion` `{"error"}` event;
  page shows ⚠️.
- Template autoescape; client links use server-provided ids; pill colors validated
  `^#[0-9a-fA-F]{6}$`.

## Testing (pytest, network mocked — CLAUDE.md conventions)

`tests/unit/test_site_learn.py`:

- **`build_messages` (pure):** `[system, user]`; system demands an ordered path,
  step-starts-with-title, plain text (no Markdown); user contains the galaxy name
  and the item titles.
- **`load_galaxies`:** seed a temp DB (reuse the full-row insert helper pattern
  from `tests/unit/test_site_mirror.py` — a `_insert_item` with all NOT NULL
  columns + `clusters` rows). Assert galaxies sorted by size desc with ids/colors,
  and each galaxy's `items` hold the cluster's id/title/summary/type; missing DB →
  `[]` and no-clusters DB → `[]`, without raising.
- **Route `POST /learn/route`** (TestClient, `llm.stream_completion` monkeypatched
  to canned deltas): known cluster streams deltas; empty/unknown cluster → `error`
  event. **`GET /learn`** returns 200, contains 「进阶路线」, the galaxy names, and
  the embedded items JSON.
- **Topbar:** page contains the `/learn` nav link.

## Out of scope (YAGNI)

- No persistence/caching of routes; no cross-galaxy or whole-corpus path.
- No reordering UI, no "mark as read"/progress (principle steers away from
  gamification/streaks).
- No new config, dependency, DB/schema change, or sync-time work.
- No embedding-based pre-ordering — the LLM sequences from titles/summaries
  (the items are already topically grouped by the cluster).

## File touch list

- **new** `src/aishelf/site/learn.py`
- **new** `src/aishelf/site/templates/learn.html`
- **new** `tests/unit/test_site_learn.py`
- **edit** `src/aishelf/site/app.py` (2 routes + `_LearnRequest`; import `learn`)
- **edit** `src/aishelf/site/templates/_topbar.html` (nav link)
- **edit** `src/aishelf/site/static/style.css` (small `.learn` block)
- **edit** `CLAUDE.md` (document `learn.py` + the two routes)

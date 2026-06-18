# 关键词宇宙 / 标签云 (keyword universe) — Design

**Date:** 2026-06-18
**Status:** Approved (autonomous-iteration; author = approver, rationale logged inline)

## Why

The last four shipped features (藏书镜, 笔记草稿, 进阶路线, 抬杠) are all the same
*shape*: click a button, stream an LLM paragraph. Time for a different shape. This
one is **pure data, no LLM** — a structural browse modality.

Atlas already has keyword chips, but they only filter **within a section**
(`/videos?keyword=X` or `/blogs?keyword=X`), and there is **no index of all
keywords** — you can't see what tags your collection even has, or everything
(videos *and* blogs) under one tag. Keywords are the richest latent structure in
the corpus and they're under-exposed.

「关键词宇宙」adds a corpus-wide tag layer: `GET /keywords` renders a **tag cloud**
of every keyword sized by frequency, and `GET /keyword/{kw}` shows **all** items —
videos and blogs together — carrying that tag. It turns inert tags into an
explorable map of your interests.

Fits the taste (简洁 + 实用 + 好玩，拒绝花里胡哨; distill rather than decorate;
reuse existing infra). **实用** = real corpus-wide discovery/navigation that didn't
exist. **好玩** = the cloud is a glanceable portrait of what you collect; one click
connects content the per-section filter siloed. A restrained, frequency-sized tag
cloud is informational, not a gimmick.

**Purely additive** — existing per-section keyword chips and their tests are left
untouched (e.g. `test_site_app.py` asserts chips link to `/videos?keyword=ai`); this
feature only *adds* a global index + a cross-type tag page.

## What it is

- `GET /keywords` — a tag-cloud index page: every distinct keyword across the whole
  corpus, font-size scaled by how many items carry it, each linking to its tag page.
- `GET /keyword/{kw}` — a cross-type list of all items (videos + blogs) carrying
  that keyword, rendered exactly like the author page. 404 when no item matches
  (mirrors `/authors/{key}`).
- A topbar 「标签」link → `/keywords`.
- No LLM, no persistence, no caching, no new config/deps. Reads files per request
  like the rest of browse.

## Architecture

### Pure aggregator (`views.py`)

```python
def keyword_counts(items: list[ContentItem]) -> list[tuple[str, int]]:
    """All distinct keywords with how many items carry each, case-insensitive
    grouping. Returns (display, count) sorted by count desc then display asc.
    `display` is the first-seen original casing for that lower-cased key."""
```

Lives in `views.py` next to `by_keyword` (the existing pure filter this feature
reuses for the tag page). Empty/keyword-less corpus → `[]`.

`by_keyword(items, kw)` is already case-insensitive and operates on **any** item
list, so `by_keyword(_items(), kw)` yields cross-type results directly — no new
filter needed.

### Routes (`app.py`)

```python
@app.get("/keywords")  -> keywords.html with tags=keyword_counts(_items()) (+ max_count)
@app.get("/keyword/{kw}") -> by_keyword(_items(), kw); 404 if empty; split videos/blogs; keyword.html with hooks
```

`/keyword/{kw}` mirrors `author_page` exactly (filter → 404-if-empty → `views.videos`
/`views.blogs` split → render with `_hooks_for(...)`). No pagination (same as the
author page; fine for a personal corpus). `{kw}` is a path param; FastAPI URL-decodes
it, and Jinja autoescapes it in the heading.

### Templates

- `keywords.html` — extends `base.html`; a `<div class="tagcloud">` of
  `<a href="/keyword/{{ kw|urlencode }}">` links, each with an inline font-size
  scaled from its count vs `max_count` (clamped to a sane min/max), and a small
  count. Empty state ("还没有关键词…") when `tags` is empty. All tag text autoescaped.
- `keyword.html` — a near-copy of `author.html`: `<h1>标签「{{ kw }}」</h1>` then the
  same `videos` grid + `blogs` list includes (`_video_card.html` / `_blog_row.html`,
  which already render `hooks` gracefully).
- Topbar: add `<a href="/keywords">标签</a>` (after 路线).

### Styling

Add a small `.tagcloud` block to `static/style.css` (flex-wrap of inline-block
links with padding/gap; font-size set inline per tag; a muted count). No new assets,
no JS — this is a static, server-rendered page.

## Tag-cloud sizing

Route passes `tags` (list of `(display, count)`) and `max_count = max(count)` (or 1
when empty). Template sets each tag's size by a linear scale, e.g.
`font-size: {{ (0.85 + 1.25 * count / max_count)|round(2) }}rem` — smallest ≈0.85rem,
largest ≈2.1rem. Pure arithmetic in the template; no precomputed buckets needed.
Tags are emitted in `keyword_counts` order (count desc), so the cloud reads
big-to-small.

## Error handling

- `GET /keyword/{kw}` with no matches → 404 (like `/authors/{key}`).
- Empty corpus → `/keywords` shows the empty state; `keyword_counts` returns `[]`,
  `max_count` defaults to 1 (no division-by-zero).
- All tag text and headings autoescaped by Jinja; `kw|urlencode` in hrefs.

## Testing (pytest — CLAUDE.md conventions; no network involved)

- **`views.keyword_counts` (pure, in `tests/unit/test_site_views.py`):** over the
  contract fixtures (`ITEMS`), assert it returns `(kw, count)` pairs, case-insensitive
  grouping (a keyword appearing in N items has count N), sorted by count desc then
  name; empty list → `[]`.
- **Routes (`tests/unit/test_site_keywords.py`, TestClient + the
  `shutil.copytree(FIXTURES, …)` + `AISHELF_DATA_DIR` fixture pattern):**
  - `GET /keywords` → 200, contains a known fixture keyword and a `/keyword/` link.
  - `GET /keyword/{kw}` for a known keyword (e.g. `ai`) → 200, contains the matching
    item's title and 「标签」heading; mixes types if applicable.
  - `GET /keyword/zzz-nope` → 404.
  - Topbar: a page contains the `/keywords` nav link.

## Out of scope (YAGNI)

- No LLM naming/summary of tags; no per-tag hooks.
- No editing/merging/renaming keywords; no keyword management.
- No pagination on the tag page (parity with the author page).
- No change to the existing per-section `?keyword=` chips/filter (kept as-is so
  current behavior + tests are untouched).
- No new config, dependency, DB/schema change, or sync-time work.

## File touch list

- **edit** `src/aishelf/site/views.py` (`keyword_counts`)
- **edit** `src/aishelf/site/app.py` (2 routes)
- **new** `src/aishelf/site/templates/keywords.html`
- **new** `src/aishelf/site/templates/keyword.html`
- **edit** `src/aishelf/site/templates/_topbar.html` (nav link)
- **edit** `src/aishelf/site/static/style.css` (small `.tagcloud` block)
- **new** `tests/unit/test_site_keywords.py`
- **edit** `tests/unit/test_site_views.py` (`keyword_counts` test)
- **edit** `CLAUDE.md` (document the routes + `keyword_counts`)

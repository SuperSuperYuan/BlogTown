# Display Site — Design Spec

**Date:** 2026-06-03
**Status:** Approved (pending spec review)

## Purpose

The second sub-project of the aishelf re-plan: a web site that presents the
content collected under the data contract. It reads contract-conforming JSON
records and shows them like a **video site + blog site** hybrid. It is built and
tested entirely against the contract (and its fixtures); it has no dependency on
Hermes.

Depends on: `docs/superpowers/specs/2026-06-03-content-contract-design.md`
(`src/aishelf/contract/`).

## Decisions (locked during brainstorming)

- **Tech stack:** FastAPI + server-rendered Jinja2 templates. No frontend build
  step. Reuses `contract.loader`.
- **Browsing model:** separate sections — a **Videos** area (thumbnail grid) and
  a **Blogs** area (article list) — each with its native layout. Shared detail
  pages, author pages, search, and keyword filtering.
- **Data freshness:** load records per request via `contract.loader.load_items`,
  so new Hermes output appears without a restart (corpus is small).

## Scope

In scope: home, videos section, blogs section, video detail, blog detail, author
page, search, keyword filtering, pagination, 404 + empty states.

Out of scope (YAGNI): authentication, comments/likes, write/admin UI, RSS,
caching layers, full article bodies (the contract stores summary + link only),
infinite scroll.

## Architecture

```
Browser
   │  HTTP GET (server-rendered HTML)
   ▼
FastAPI app (src/aishelf/site/app.py)
   │  per request:
   ├─ contract.loader.load_items(DATA_DIR)   → list[ContentItem]
   ├─ site.views (pure functions)            → split / filter / search / group / paginate
   └─ Jinja2 templates                       → HTML
```

- `DATA_DIR` is read from the `AISHELF_DATA_DIR` env var, defaulting to the
  repo's `data/` directory.
- All non-trivial logic lives in `site/views.py` as **pure functions** operating
  on `list[ContentItem]`, so it is unit-testable without HTTP.

## Routes / Pages

| Route | Page |
|---|---|
| `GET /` | Home: latest N videos + latest N blogs as previews, links into each section |
| `GET /videos` | Video grid (thumbnail, title, author, duration), newest first, paginated; honours `?keyword=` and `?q=` |
| `GET /blogs` | Blog list (cover, title, author, date, summary), newest first, paginated; honours `?keyword=` and `?q=` |
| `GET /videos/{id}` | Video detail: embedded player if `embed_url` present, else thumbnail + "去原站观看" link; title, author (links to author page), published date, summary, clickable keywords |
| `GET /blogs/{id}` | Blog detail: cover, title, author (link), date, `site_name`, summary, clickable keywords, "阅读全文(原站)" link to `source_url` |
| `GET /authors/{key}` | Author page: that author's videos + blogs |
| `GET /search?q=` | Search results across both modalities, grouped by type |

### Query parameters

- `?page=<n>` — 1-based page index on `/videos`, `/blogs`, `/search`.
- `?keyword=<kw>` — filter a section to items whose `keywords` contain `kw`.
- `?q=<text>` — free-text search (see below).

### Identity & linking

- **Author key:** `author_id` when present, else the `author` display name. Author
  page URLs use the URL-encoded key. Clickable author names link to
  `/authors/{key}`.
- **Keywords** render as links to the current section filtered by that keyword
  (e.g. a keyword on a video detail links to `/videos?keyword=<kw>`).

## View Functions (`site/views.py`)

Pure functions over `list[ContentItem]`:

- `videos(items)` / `blogs(items)` — filter by `type` (input is assumed already
  sorted newest-first by the loader).
- `search(items, q)` — case-insensitive substring match of `q` against `title`,
  `summary`, and any `keywords` entry; returns matching items (both modalities).
- `by_keyword(items, kw)` — items whose `keywords` contain `kw` (case-insensitive
  exact match of a keyword entry).
- `author_key(item)` — returns `author_id or author`.
- `by_author(items, key)` — items whose `author_key` equals `key`.
- `paginate(items, page, per_page)` — returns a small `Page` value object with
  `items`, `page`, `per_page`, `total`, `total_pages`, `has_prev`, `has_next`.
  Out-of-range pages clamp to the valid range; empty input yields an empty page.

## Defaults

- Pagination: 24 videos/page, 20 blogs/page; search 20/page.
- Video playback: embed when `embed_url` is set, otherwise link to `source_url`.
- Search is global (both modalities), results grouped by type.
- Home preview rows: latest 8 videos, latest 8 blogs.

## Error Handling

- Unknown `{id}` on a detail page → HTTP 404 rendered with a friendly page.
- Empty `DATA_DIR` (or a section with no items) → a friendly "暂无内容" state, not
  an error.
- Malformed record files are already skipped by `contract.loader` (logged), so a
  single bad file never breaks a page.

## Components / Files

- `src/aishelf/site/__init__.py`
- `src/aishelf/site/config.py` — `get_data_dir()` from `AISHELF_DATA_DIR`.
- `src/aishelf/site/views.py` — the pure view functions above + `Page`.
- `src/aishelf/site/app.py` — FastAPI app and routes.
- `src/aishelf/site/__main__.py` — `python -m aishelf.site` (uvicorn launcher).
- `src/aishelf/site/templates/{base,home,videos,blogs,video_detail,blog_detail,author,search,not_found}.html`
- `src/aishelf/site/static/style.css`

## Testing

- **views.py:** unit tests against `tests/fixtures/contract/` for `videos`/`blogs`
  split, `search` (hit in title vs summary vs keyword; case-insensitive; miss),
  `by_keyword`, `by_author` (incl. `author_id`-vs-name grouping), and `paginate`
  (first/middle/last page, out-of-range clamp, empty input).
- **Routes:** `TestClient` with `AISHELF_DATA_DIR` pointed at
  `tests/fixtures/contract/`. Assert: `/`, `/videos`, `/blogs`, a valid
  `/videos/{id}` and `/blogs/{id}`, `/authors/{key}`, and `/search?q=` all return
  200 with expected content; an unknown detail id returns 404; an empty data dir
  renders the empty state (200, not 500).
- No Hermes / network in any test.

## Success Criteria

- `python -m aishelf.site` starts the server with no errors.
- Against the fixtures, the videos grid and blogs list render their items
  newest-first; detail, author, and search pages work; keyword links filter.
- An unknown id yields 404; an empty data dir yields the empty state.
- All unit and route tests pass.

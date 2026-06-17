# 「今日速读」(Daily Digest) — Design

**Date:** 2026-06-17
**Status:** Approved, ready for implementation plan
**Roadmap position:** Idea **C** of the A→B→C evolution (A 一句话钩子 ✅ → B 灵感碰撞 ✅ → **C 今日速读**). C makes the home page a reason to return.

## Problem

Atlas now collects, makes each item legible (A's hook), and lets you collide ideas
(B). But the home page is still a static "latest videos / latest blogs" split —
there's no single glance that says *what's new and worth your time today*. C adds a
lightweight daily-driver card, staying 简洁: it **reuses A's stored hooks** as the
per-item "why" and adds **no LLM call, no caching, no new config**.

## Goal

A `今日速读` card at the top of the home page showing the most recently *collected*
items plus one resurfaced older "gem", each with its existing one-line hook. Pure
assembly from data already loaded per request.

## Locked design decisions

- **Content:** a curated list — recent collections + one older gem — each showing
  A's stored hook as the "why". **No synthesized overview blurb, no LLM call, no
  caching.**
- **Gem:** exactly one per day, chosen by a **date-seeded** random pick from the
  older items (`random.Random(today).choice(...)`), so it is stable all day and
  rotates tomorrow. No persistence.
- **Recency:** sort by `collected_at` descending (true recency — note the normal
  home/loader sort is `published_at`). `recent_n = 5`.
- **No new config; no new page** (lives on `/`); no read/dismiss state.

## Architecture

A pure assembly function (`digest.build_digest`) mirrors the `views.py` /
`collide.py` pure-logic pattern. The home route builds the digest from the
already-loaded `_items()` plus `_hooks_for(...)` (A's existing `db.search.hooks_for`
bridge — no new DB query) and passes it to `home.html`.

### New module `src/aishelf/site/digest.py`

```python
@dataclass
class Entry:
    item: ContentItem
    hook: str          # "" when no hook is available

@dataclass
class Digest:
    recent: list[Entry]
    gem: Entry | None

def build_digest(items, hooks, *, today, recent_n=5) -> Digest: ...
```

- `items`: the full `list[ContentItem]` (any order). `hooks`: `{id: hook}` map.
  `today`: a date string used as the gem's random seed (passed in → pure +
  deterministic).
- Sort a copy of `items` by `collected_at` descending. Sorting key parses the ISO
  timestamp (reuse the loader's tolerant parse so an unparseable value sorts last);
  ties broken by `id` for stability.
- `recent` = the first `recent_n` sorted items, each wrapped as
  `Entry(item, hooks.get(item.id, ""))`.
- `older` = the remaining sorted items. `gem` = `Entry` for
  `random.Random(today).choice(older)` when `older` is non-empty, else `None`.
- `recent` and `gem` are disjoint (gem is drawn only from items beyond `recent_n`).
- Empty `items` → `Digest(recent=[], gem=None)`.

### Home route (`src/aishelf/site/app.py`)

The existing `home` route already loads `items` and (after A) can call
`_hooks_for`. Build the digest over the **full** item list (not just the preview
slices) and add it to the template context:

```python
items = _items()
hooks = _hooks_for(items)            # one call; superset map reused below (DRY)
vids = views.videos(items)[:HOME_PREVIEW]
blogs = views.blogs(items)[:HOME_PREVIEW]
digest = digest_mod.build_digest(items, hooks, today=date.today().isoformat())
return templates.TemplateResponse(request, "home.html",
    {"videos": vids, "blogs": blogs, "hooks": hooks, "digest": digest})
```

(Import `from datetime import date` and add `digest as digest_mod` to the existing `from aishelf.site import (...)` tuple. A single `_hooks_for(items)` call serves both the digest and the browse cards — the browse partials look up by id, so a superset map is fine.)

### `home.html`

Add a `今日速读` `<section class="digest">` **above** the 最新视频 section, rendered
only when `digest.recent` is non-empty:

- Heading `今日速读`.
- The recent list: each entry a row with a title link (`/videos/{id}` or
  `/blogs/{id}`), a small type/date meta line, and the hook (when present).
- The gem, visually set apart (e.g. a `翻出来` label), with its hook — rendered
  only when `digest.gem` is not null.

Guard every hook with `{% if e.hook %}`. Autoescaped (hook/title are plain text).

### `style.css`

A few `.digest` rules: the card container, recent rows, and the highlighted gem
block. Reuse existing color tokens (`#0a84ff` accent, muted grays).

## Data flow

```
GET / → _items() (files) → _hooks_for(items) ({id: hook}, A's bridge)
      → digest.build_digest(items, hooks, today=date.today().isoformat())
      → home.html renders the 今日速读 card (recent rows + gem)
```

## Degradation

- **No hooks** (`ATLAS_CHAT_*` unset → empty hooks map): entries render title + meta
  only; the card still works as a recency list.
- **`<1` item**: card hidden (the rest of home already shows 暂无内容).
- **Fewer than `recent_n` items**: show what exists; no `older` ⇒ no gem.
- All reads are best-effort (`_hooks_for` already tolerates a missing/old DB → `{}`).

## Testing

- **`build_digest`** (pure): sorts by `collected_at` descending; respects
  `recent_n` (recent has at most `recent_n`); gem is date-seeded deterministic
  (same `today` → same gem across calls); gem is drawn from items beyond `recent_n`
  and never appears in `recent`; gem is `None` when there is no older item; hooks
  are attached from the map (and default to `""` when absent); empty `items` →
  empty `Digest`.
- **Home route**: the card lists recent items and the gem; a hook is rendered when
  present; the page renders fine with no hooks and with fewer than `recent_n` items;
  the card is absent when there are no items.

## Non-goals (YAGNI)

- No synthesized overview blurb (would need an LLM call + daily caching).
- No caching layer (pure per-request assembly is fast at personal-library scale).
- No new environment variable; not its own route/page (it lives on `/`).
- No read/seen/dismiss state.

## Files

- Create: `src/aishelf/site/digest.py`, `tests/unit/test_digest.py`.
- Modify: `src/aishelf/site/app.py` (home route), `src/aishelf/site/templates/home.html`,
  `src/aishelf/site/static/style.css`, `tests/unit/test_site_app.py`.
- `CLAUDE.md`: document `digest.py` + the home-card behavior.

## Documentation touch-ups (on implementation)

- `CLAUDE.md`: note `aishelf/site/digest.py` (pure `build_digest` — recent-by-
  `collected_at` + a date-seeded gem, reusing A's hooks; no LLM/cache) and that the
  home page renders a 今日速读 card.

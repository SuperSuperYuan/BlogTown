# 「今日速读」(Daily Digest) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 今日速读 card at the top of the home page listing the most recently *collected* items plus one date-seeded older "gem", each with its existing A-hook — pure assembly, no LLM, no caching.

**Architecture:** A pure `digest.build_digest(items, hooks, *, today, recent_n)` (mirroring the `views.py`/`collide.py` pure-logic pattern) sorts by `collected_at`, takes the recent N, and picks one gem from the older remainder via `random.Random(today)`. The home route feeds it the already-loaded items + A's `_hooks_for` map and renders a card in `home.html`.

**Tech Stack:** Python (stdlib `random`/`datetime`), FastAPI + Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-06-17-daily-digest-design.md`

---

## File Structure

- `src/aishelf/site/digest.py` (new) — `Entry`, `Digest` dataclasses + pure `build_digest`.
- `src/aishelf/site/app.py` — home route: build the digest, pass it (and a single `_hooks_for(items)` map) to the template.
- `src/aishelf/site/templates/home.html` — 今日速读 card above the existing sections.
- `src/aishelf/site/static/style.css` — `.digest` styles.
- Tests: `tests/unit/test_digest.py` (new), `tests/unit/test_site_app.py` (home card).
- `CLAUDE.md` — document `digest.py` + the home card.

---

## Task 1: `digest.py` — pure `build_digest`

**Files:**
- Create: `src/aishelf/site/digest.py`
- Test: `tests/unit/test_digest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_digest.py`:

```python
from types import SimpleNamespace

from aishelf.site import digest as digest_mod


def _it(id, collected_at, type="video", title="T"):
    return SimpleNamespace(id=id, collected_at=collected_at, type=type, title=title)


def test_recent_sorted_by_collected_desc():
    items = [_it("a", "2024-01-01T00:00:00"),
             _it("b", "2024-03-01T00:00:00"),
             _it("c", "2024-02-01T00:00:00")]
    d = digest_mod.build_digest(items, {}, today="2026-06-17", recent_n=2)
    assert [e.item.id for e in d.recent] == ["b", "c"]


def test_recent_n_limit_and_gem_from_older():
    items = [_it(f"i{n}", f"2024-01-{n:02d}T00:00:00") for n in range(1, 8)]  # i1..i7
    d = digest_mod.build_digest(items, {}, today="2026-06-17", recent_n=5)
    recent_ids = {e.item.id for e in d.recent}
    assert len(d.recent) == 5
    assert recent_ids == {"i7", "i6", "i5", "i4", "i3"}      # 5 most recent
    assert d.gem is not None
    assert d.gem.item.id in {"i2", "i1"}                     # gem from older
    assert d.gem.item.id not in recent_ids                   # disjoint


def test_gem_deterministic_per_today():
    items = [_it(f"i{n}", f"2024-01-{n:02d}T00:00:00") for n in range(1, 10)]
    a = digest_mod.build_digest(items, {}, today="2026-06-17")
    b = digest_mod.build_digest(items, {}, today="2026-06-17")
    assert a.gem.item.id == b.gem.item.id                    # same day -> same gem
    c = digest_mod.build_digest(items, {}, today="2026-06-18")
    assert c.gem.item.id not in {e.item.id for e in c.recent}  # still a valid older pick


def test_no_gem_when_no_older():
    items = [_it("a", "2024-01-02T00:00:00"), _it("b", "2024-01-01T00:00:00")]
    d = digest_mod.build_digest(items, {}, today="2026-06-17", recent_n=5)
    assert len(d.recent) == 2 and d.gem is None


def test_hooks_attached_with_blank_default():
    items = [_it("a", "2024-01-02T00:00:00"), _it("b", "2024-01-01T00:00:00")]
    d = digest_mod.build_digest(items, {"a": "钩子A"}, today="2026-06-17", recent_n=5)
    by = {e.item.id: e.hook for e in d.recent}
    assert by["a"] == "钩子A" and by["b"] == ""


def test_empty_items():
    d = digest_mod.build_digest([], {}, today="2026-06-17")
    assert d.recent == [] and d.gem is None


def test_unparseable_collected_at_sorts_last():
    items = [_it("good", "2024-05-01T00:00:00"), _it("bad", "not-a-date")]
    d = digest_mod.build_digest(items, {}, today="2026-06-17", recent_n=5)
    assert [e.item.id for e in d.recent] == ["good", "bad"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_digest.py -v`
Expected: FAIL with `ImportError` / `AttributeError` (no `aishelf.site.digest` / no `build_digest`).

- [ ] **Step 3: Implement the module**

Create `src/aishelf/site/digest.py`:

```python
"""Daily-digest assembly for the home page (pure).

Recent-by-collected_at items + one date-seeded "gem" from the older remainder,
each carrying its A-generated hook. No LLM, no caching — pure per-request
assembly. Mirrors the views.py / collide.py pure-logic pattern.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Entry:
    item: object       # a ContentItem (only .id/.type/.title/.collected_at are read)
    hook: str          # "" when no hook is available


@dataclass
class Digest:
    recent: list
    gem: "Entry | None"


def _collected_key(it):
    """ISO collected_at -> naive-UTC datetime for sorting; unparseable sorts last.

    Normalizes tz-aware values to naive UTC so a mix of aware/naive timestamps
    never raises when compared (same approach as the contract loader)."""
    raw = getattr(it, "collected_at", "") or ""
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def build_digest(items, hooks, *, today, recent_n=5) -> Digest:
    """Recent collections + one date-seeded older gem, each with its hook.

    `items`: ContentItems (any order). `hooks`: {id: hook}. `today`: a date
    string seeding the gem so it is stable within a day. `recent` holds the
    `recent_n` most recently collected; `gem` is one random pick from the rest
    (None when there is none); the two are disjoint.
    """
    ordered = sorted(items, key=lambda it: (_collected_key(it), it.id), reverse=True)
    recent = [Entry(it, hooks.get(it.id, "")) for it in ordered[:recent_n]]
    older = ordered[recent_n:]
    gem = None
    if older:
        pick = random.Random(today).choice(older)
        gem = Entry(pick, hooks.get(pick.id, ""))
    return Digest(recent=recent, gem=gem)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_digest.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/digest.py tests/unit/test_digest.py
git commit -m "feat(digest): pure build_digest (recent + date-seeded gem)"
```

---

## Task 2: Wire the digest into the home page

**Files:**
- Modify: `src/aishelf/site/app.py` (imports + `home` route)
- Modify: `src/aishelf/site/templates/home.html`, `src/aishelf/site/static/style.css`
- Test: `tests/unit/test_site_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_site_app.py`:

```python
import json as _dj
from fastapi.testclient import TestClient as _DClient


def _seed_one_video(tmp_path, vid="v1", title="速读测试视频", collected="2026-06-10T00:00:00"):
    rec = {"id": vid, "type": "video", "title": title, "author": "作者甲",
           "platform": "youtube", "source_url": f"https://x/{vid}",
           "published_at": "2024-01-01", "summary": "摘要", "keywords": [],
           "collected_at": collected, "thumbnail_url": "https://img/x.jpg"}
    (tmp_path / "videos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "videos" / f"{vid}.json").write_text(_dj.dumps(rec, ensure_ascii=False), encoding="utf-8")


def test_home_shows_digest_card_with_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    _seed_one_video(tmp_path)
    from aishelf.db.sync import sync
    from aishelf.db import schema
    sync(tmp_path, tmp_path / "atlas.db")
    con = schema.connect(tmp_path / "atlas.db")
    con.execute("UPDATE items SET hook=? WHERE id=?", ("速读钩子", "v1"))
    con.commit()
    con.close()
    from aishelf.site.app import app
    r = _DClient(app).get("/")
    assert r.status_code == 200
    assert "今日速读" in r.text
    assert "速读测试视频" in r.text
    assert "速读钩子" in r.text


def test_home_digest_absent_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")   # no items
    from aishelf.site.app import app
    r = _DClient(app).get("/")
    assert r.status_code == 200
    assert "今日速读" not in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_site_app.py -k digest -v`
Expected: `test_home_shows_digest_card_with_hook` FAILs ("今日速读"/title/hook not in HTML — the route/template don't build it yet). `test_home_digest_absent_when_empty` may already pass.

- [ ] **Step 3: Add imports in `app.py`**

In `src/aishelf/site/app.py`: add `from datetime import date` near the top imports (after the existing `from contextlib import asynccontextmanager` / `from dataclasses import asdict, replace` group). Then, immediately after the `from aishelf.site import (...)` block, add:

```python
from aishelf.site import digest as digest_mod
```

- [ ] **Step 4: Update the `home` route**

Replace the current `home` route body:

```python
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    items = _items()
    vids = views.videos(items)[:HOME_PREVIEW]
    blogs = views.blogs(items)[:HOME_PREVIEW]
    return templates.TemplateResponse(
        request,
        "home.html",
        {"videos": vids, "blogs": blogs, "hooks": _hooks_for(vids + blogs)},
    )
```

with:

```python
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    items = _items()
    hooks = _hooks_for(items)            # one call; superset map reused below
    vids = views.videos(items)[:HOME_PREVIEW]
    blogs = views.blogs(items)[:HOME_PREVIEW]
    daily = digest_mod.build_digest(items, hooks, today=date.today().isoformat())
    return templates.TemplateResponse(
        request,
        "home.html",
        {"videos": vids, "blogs": blogs, "hooks": hooks, "digest": daily},
    )
```

- [ ] **Step 5: Add the card to `home.html`**

In `src/aishelf/site/templates/home.html`, insert this block immediately after `{% block content %}` (above the 最新视频 `<section>`):

```html
{% if digest and digest.recent %}
<section class="digest">
  <h2>今日速读</h2>
  <ul class="digest-list">
    {% for e in digest.recent %}
    <li class="digest-item">
      <a class="d-title" href="{{ '/videos/' if e.item.type == 'video' else '/blogs/' }}{{ e.item.id }}">{{ e.item.title }}</a>
      <span class="d-meta">{{ '视频' if e.item.type == 'video' else '博客' }} · {{ e.item.collected_at[:10] }}</span>
      {% if e.hook %}<p class="d-hook">{{ e.hook }}</p>{% endif %}
    </li>
    {% endfor %}
  </ul>
  {% if digest.gem %}
  <div class="digest-gem">
    <span class="gem-label">翻出来</span>
    <a class="d-title" href="{{ '/videos/' if digest.gem.item.type == 'video' else '/blogs/' }}{{ digest.gem.item.id }}">{{ digest.gem.item.title }}</a>
    {% if digest.gem.hook %}<p class="d-hook">{{ digest.gem.hook }}</p>{% endif %}
  </div>
  {% endif %}
</section>
{% endif %}
```

- [ ] **Step 6: Add styles**

Append to `src/aishelf/site/static/style.css`:

```css
.digest { background: #fafbfc; border: 1px solid #e7e9ef; border-radius: 12px; padding: 14px 16px; margin-bottom: 18px; }
.digest h2 { margin: 0 0 8px; font-size: 16px; }
.digest-list { list-style: none; margin: 0; padding: 0; }
.digest-item { padding: 6px 0; border-bottom: 1px solid #eef0f3; }
.digest-item:last-child { border-bottom: none; }
.digest .d-title { font-weight: 600; color: #1f2933; text-decoration: none; }
.digest .d-title:hover { color: #0a84ff; }
.digest .d-meta { margin-left: 8px; font-size: 12px; color: #7b8794; }
.digest .d-hook { margin: 2px 0 0; color: #3e4c59; font-size: 13px; }
.digest-gem { margin-top: 10px; padding-top: 10px; border-top: 2px solid #e7e9ef; }
.digest-gem .gem-label { display: inline-block; font-size: 12px; color: #0a84ff; margin-right: 6px; font-weight: 600; }
```

- [ ] **Step 7: Run the home tests + full suite**

Run: `pytest tests/unit/test_site_app.py -v` then `pytest -q`
Expected: PASS (the 2 new digest tests + all pre-existing app tests + whole suite green).

- [ ] **Step 8: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/home.html src/aishelf/site/static/style.css tests/unit/test_site_app.py
git commit -m "feat(site): 今日速读 home card (recent + date-seeded gem)"
```

---

## Task 3: Documentation + full-suite verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

In the `aishelf/site/` architecture bullet (the module list naming `app.py`, `views.py`, `collide.py`, etc.), add a terse `digest.py` entry, weaving into the existing style (not a new section):

`digest.py` (今日速读: pure `build_digest` — recent items by `collected_at` + one date-seeded older "gem", each carrying its A-hook; no LLM/cache; rendered as a home-page card)

If there's a place describing the home page (`/`), add that it renders a 今日速读 card. Verify every claim against `digest.py` and the `home` route before committing.

- [ ] **Step 2: Run the full test suite**

Run: `pytest -q`
Expected: PASS (network tests skipped by default).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document 今日速读 (digest.py, home card)"
```

---

## Self-Review

- **Spec coverage:** pure `build_digest` with recent-by-`collected_at` + date-seeded gem + hook attachment + disjoint recent/gem + `None`-when-no-older + empty handling (Task 1) ✓; `recent_n=5` default (Task 1 signature) ✓; one `_hooks_for(items)` call reused for digest + browse cards (Task 2 route) ✓; home card above existing sections, hidden when empty, hook guarded, gem guarded (Task 2 template) ✓; degradation — no hooks → blank `.hook` (Entry default `""` + `{% if e.hook %}`), `<recent_n` items → no gem, no items → no card (Tasks 1–2) ✓; styles (Task 2) ✓; docs (Task 3) ✓. Non-goals (no overview blurb, no cache, no new env, no own page, no read state) — no task adds them.
- **Placeholder scan:** none — every code step has full code; every run step has a command + expected outcome.
- **Type consistency:** `build_digest(items, hooks, *, today, recent_n=5) -> Digest`; `Digest(recent: list[Entry], gem: Entry | None)`; `Entry(item, hook)`; template reads `digest.recent`, `e.item.type/.id/.title/.collected_at`, `e.hook`, `digest.gem.item.*`/`digest.gem.hook` — all consistent across tasks. Route passes context key `"digest"` matching the template's `digest`. Module imported as `digest_mod`; local var named `daily` to avoid shadowing the module.

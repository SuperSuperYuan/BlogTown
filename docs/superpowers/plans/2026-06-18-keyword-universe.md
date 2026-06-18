# 关键词宇宙 / 标签云 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a corpus-wide keyword layer: a `GET /keywords` tag cloud (sized by frequency) and a `GET /keyword/{kw}` page listing all items (videos + blogs) under one tag.

**Architecture:** A pure aggregator `views.keyword_counts` over the per-request item list; two server-rendered routes reusing `views.by_keyword` (cross-type filter, already exists), the author-page render pattern (`views.videos`/`views.blogs` + `_hooks_for`), and existing card/row partials. Pure data — no LLM, no persistence, no new config/deps. Purely additive: existing per-section `?keyword=` chips/tests untouched.

**Tech Stack:** Python 3, FastAPI, Jinja2, pytest + FastAPI TestClient.

---

### Task 1: `views.keyword_counts` (pure)

**Files:**
- Modify: `src/aishelf/site/views.py`
- Test: `tests/unit/test_site_views.py`

- [ ] **Step 1: Write the failing tests** — APPEND to `tests/unit/test_site_views.py`:

```python
from types import SimpleNamespace


def _kw_item(*kws):
    return SimpleNamespace(keywords=list(kws))


def test_keyword_counts_groups_case_insensitively_and_sorts():
    items = [_kw_item("AI", "ml"), _kw_item("ai", "RAG"), _kw_item("ml")]
    res = views.keyword_counts(items)
    # ai (AI/ai merged) -> 2, ml -> 2, RAG -> 1; ties broken by name asc;
    # display is the first-seen original casing for each lower-cased key
    assert res == [("AI", 2), ("ml", 2), ("RAG", 1)]


def test_keyword_counts_dedupes_within_one_item():
    res = views.keyword_counts([_kw_item("ai", "AI", "ai")])
    assert res == [("ai", 1)]   # same keyword repeated in one item counts once


def test_keyword_counts_empty():
    assert views.keyword_counts([]) == []


def test_keyword_counts_over_fixtures():
    res = views.keyword_counts(ITEMS)   # ai, llm, research, agents — each in 1 item
    assert dict(res) == {"ai": 1, "llm": 1, "research": 1, "agents": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_site_views.py -k keyword_counts -v`
Expected: FAIL — `AttributeError: module 'aishelf.site.views' has no attribute 'keyword_counts'`.

- [ ] **Step 3: Add `keyword_counts` to `src/aishelf/site/views.py`** (next to `by_keyword`):

```python
def keyword_counts(items: list) -> list[tuple[str, int]]:
    """All distinct keywords with how many items carry each (case-insensitive
    grouping; a keyword repeated within one item counts once). Returns
    (display, count) sorted by count desc then display (case-insensitive) asc;
    `display` is the first-seen original casing for that lower-cased key."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for it in items:
        seen: set[str] = set()
        for k in getattr(it, "keywords", None) or []:
            key = k.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, k)
    pairs = [(display[k], counts[k]) for k in counts]
    pairs.sort(key=lambda p: (-p[1], p[0].lower()))
    return pairs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_views.py -k keyword_counts -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/views.py tests/unit/test_site_views.py
git commit -m "feat(site): views.keyword_counts（跨类型关键词计数）"
```

---

### Task 2: `GET /keyword/{kw}` + `keyword.html`

**Files:**
- Modify: `src/aishelf/site/app.py` (add route near `author_page`, ~line 338)
- Create: `src/aishelf/site/templates/keyword.html`
- Test: `tests/unit/test_site_keywords.py`

- [ ] **Step 1: Write the failing tests** (create `tests/unit/test_site_keywords.py`):

```python
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    from aishelf.site.app import app
    return TestClient(app)


def test_keyword_page_lists_matching_items(client):
    r = client.get("/keyword/ai")
    assert r.status_code == 200
    assert "标签" in r.text
    assert "youtube-aaa" in r.text          # the matching video's card href


def test_keyword_page_is_cross_type(client):
    # 'research' is on a blog in fixtures
    r = client.get("/keyword/research")
    assert r.status_code == 200
    assert "blog-ccc" in r.text


def test_keyword_page_unknown_is_404(client):
    assert client.get("/keyword/zzz-nope").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_site_keywords.py -k keyword_page -v`
Expected: FAIL — `/keyword/ai` 404 (no route/template).

- [ ] **Step 3a: Create `src/aishelf/site/templates/keyword.html`** (mirrors `author.html`):

```html
{% extends "base.html" %}
{% block title %}标签「{{ kw }}」· Atlas{% endblock %}
{% block content %}
<h1>标签「{{ kw }}」</h1>
{% if videos %}<h2>视频</h2><div class="grid">{% for it in videos %}{% include "_video_card.html" %}{% endfor %}</div>{% endif %}
{% if blogs %}<h2>博客</h2><ul class="bloglist">{% for it in blogs %}{% include "_blog_row.html" %}{% endfor %}</ul>{% endif %}
{% endblock %}
```

- [ ] **Step 3b: Add the route to `app.py`** immediately after `author_page` (~line 349):

```python
@app.get("/keyword/{kw}", response_class=HTMLResponse)
def keyword_page(request: Request, kw: str):
    mine = views.by_keyword(_items(), kw)
    if not mine:
        raise HTTPException(status_code=404)
    vids = views.videos(mine)
    blogs = views.blogs(mine)
    return templates.TemplateResponse(
        request,
        "keyword.html",
        {"kw": kw, "videos": vids, "blogs": blogs, "hooks": _hooks_for(vids + blogs)},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_keywords.py -v`
Expected: PASS. Then `python -m pytest -q` — whole suite green.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/keyword.html tests/unit/test_site_keywords.py
git commit -m "feat(site): GET /keyword/{kw}（跨类型标签页）"
```

---

### Task 3: `GET /keywords` tag cloud + topbar + CSS

**Files:**
- Modify: `src/aishelf/site/app.py` (add route; near the new `keyword_page`)
- Create: `src/aishelf/site/templates/keywords.html`
- Modify: `src/aishelf/site/templates/_topbar.html` (nav link)
- Modify: `src/aishelf/site/static/style.css` (small `.kw-cloud` block)
- Test: `tests/unit/test_site_keywords.py`

- [ ] **Step 1: Write the failing tests** — APPEND to `tests/unit/test_site_keywords.py`:

```python
def test_keywords_index_renders_cloud(client):
    r = client.get("/keywords")
    assert r.status_code == 200
    assert "关键词宇宙" in r.text
    assert "ai" in r.text                       # a fixture keyword
    assert "/keyword/ai" in r.text              # links to the tag page


def test_topbar_has_keywords_link(client):
    r = client.get("/keywords")
    assert 'href="/keywords"' in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_site_keywords.py -k "index or topbar" -v`
Expected: FAIL — `/keywords` 404; no topbar link.

- [ ] **Step 3a: Add the route to `app.py`** (right after `keyword_page`):

```python
@app.get("/keywords", response_class=HTMLResponse)
def keywords_page(request: Request):
    tags = views.keyword_counts(_items())
    max_count = max((c for _, c in tags), default=1)
    return templates.TemplateResponse(
        request, "keywords.html", {"tags": tags, "max_count": max_count}
    )
```

- [ ] **Step 3b: Create `src/aishelf/site/templates/keywords.html`:**

```html
{% extends "base.html" %}
{% block title %}关键词宇宙 · Atlas{% endblock %}
{% block content %}
<section class="kw-cloud">
  <h1>关键词宇宙 <span class="hint">点一个标签，看看它串起了哪些内容</span></h1>
  {% if tags %}
  <div class="tagcloud">
    {% for kw, count in tags %}
    <a href="/keyword/{{ kw|urlencode }}" style="font-size: {{ (0.85 + 1.25 * count / max_count)|round(2) }}rem">{{ kw }}<span class="tc-count">{{ count }}</span></a>
    {% endfor %}
  </div>
  {% else %}
  <p class="empty">还没有关键词——采集一些内容后再来。</p>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 3c: Add the nav link in `_topbar.html`** — change the `<nav>` line to add
`<a href="/keywords">标签</a>` right after `<a href="/learn">路线</a>`:

```html
<nav><a href="/videos">视频</a><a href="/blogs">博客</a><a href="/write">写博客</a><a href="/ask">问答</a><a href="/graph">图谱</a><a href="/collide">碰撞</a><a href="/mirror">镜子</a><a href="/learn">路线</a><a href="/keywords">标签</a><a href="/collect">Hermes</a></nav>
```

- [ ] **Step 3d: Append a `.kw-cloud` block to `static/style.css`:**

```css
/* 关键词宇宙 / 标签云 */
.kw-cloud h1 .hint { font-size: .5em; font-weight: 400; color: #8a8f98; margin-left: .5em; }
.kw-cloud .tagcloud {
  display: flex; flex-wrap: wrap; gap: .5rem 1.1rem; align-items: baseline;
  margin-top: 1.3rem; line-height: 1.7;
}
.kw-cloud .tagcloud a { color: #cdd3da; text-decoration: none; }
.kw-cloud .tagcloud a:hover { color: #8ab4ff; }
.kw-cloud .tc-count { font-size: .55em; color: #8a8f98; margin-left: .12em; vertical-align: super; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_keywords.py -v`
Expected: PASS (all). Then `python -m pytest -q` — whole suite green.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/keywords.html src/aishelf/site/templates/_topbar.html src/aishelf/site/static/style.css tests/unit/test_site_keywords.py
git commit -m "feat(site): GET /keywords 标签云 + 标签导航"
```

---

### Task 4: Docs — update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document the routes** — find the browse/endpoint prose (near the
`/authors/{key}` / search description, or the `GET /api/search` paragraph) and add:

```
`GET /keywords` renders a corpus-wide 标签云 (tag cloud sized by frequency, pure
data, no LLM) via `views.keyword_counts`; `GET /keyword/{kw}` lists all items
(videos + blogs) carrying a tag (cross-type, reusing `views.by_keyword`; 404 when
none) — complementing the existing per-section `?keyword=` filter.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 关键词宇宙/标签云（GET /keywords + GET /keyword/{kw}）"
```

---

## Self-Review

**1. Spec coverage:**
- `views.keyword_counts` (pure, case-insensitive grouping, dedupe-within-item, sort) → Task 1 ✓
- `GET /keyword/{kw}` cross-type page (reuse by_keyword + author render + hooks, 404) → Task 2 ✓
- `GET /keywords` tag cloud (frequency sizing) + topbar + CSS → Task 3 ✓
- Tests: keyword_counts (synthetic + fixtures), keyword page (match/cross-type/404), cloud index, topbar → Tasks 1–3 ✓
- CLAUDE.md → Task 4 ✓
- Out-of-scope honored (no LLM, no keyword mgmt, no pagination, per-section chips untouched, no new config/deps/DB) ✓

**2. Placeholder scan:** No TBD/TODO; every code step has full code. ✓

**3. Type consistency:** `keyword_counts(items) -> list[(display:str, count:int)]` used by
the `/keywords` route (`tags`, `max_count`) and `keywords.html` (`for kw, count in tags`,
`count / max_count`). `/keyword/{kw}` reuses `views.by_keyword`/`views.videos`/`views.blogs`/
`_hooks_for` (all exist) and renders `keyword.html` with `{kw, videos, blogs, hooks}` —
exactly `author.html`'s shape (+ `kw`). Route paths `/keywords` and `/keyword/{kw}` are
distinct (no FastAPI collision). Fixture-based assertions use real keywords (`ai`→
youtube-aaa, `research`→blog-ccc) and item ids that appear in card/row hrefs. ✓

# Display Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI + Jinja2 site that reads contract records and presents them as a video-site + blog-site hybrid (separate sections, shared detail/author/search/keyword pages).

**Architecture:** Each request loads all records via `contract.loader.load_items(DATA_DIR)`; pure functions in `site/views.py` split/filter/search/group/paginate them; Jinja2 templates render server-side HTML. No frontend build step. Built and tested entirely against `tests/fixtures/contract/`.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, uvicorn, pytest + FastAPI `TestClient`.

**Spec:** `docs/superpowers/specs/2026-06-03-display-site-design.md`

**Commands:** use `.venv/bin/python` / `.venv/bin/pytest`. Append to every commit body: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- Modify: `pyproject.toml` — add `jinja2`.
- Create: `src/aishelf/site/__init__.py`
- Create: `src/aishelf/site/config.py` — `get_data_dir()`.
- Create: `src/aishelf/site/views.py` — `Page` + pure view functions.
- Create: `src/aishelf/site/app.py` — FastAPI routes + Jinja setup + 404 handler.
- Create: `src/aishelf/site/__main__.py` — uvicorn launcher.
- Create: `src/aishelf/site/templates/{base,home,videos,blogs,video_detail,blog_detail,author,search,not_found,_video_card,_blog_row,_pager,_keywords}.html`
- Create: `src/aishelf/site/static/style.css`
- Create: `tests/unit/test_site_views.py`, `tests/unit/test_site_app.py`

---

## Task 1: Dependency + config

**Files:**
- Modify: `pyproject.toml`
- Create: `src/aishelf/site/__init__.py`
- Create: `src/aishelf/site/config.py`

- [ ] **Step 1: Add jinja2 dependency**

In `pyproject.toml`, in the `dependencies` array, add this line after the `uvicorn[standard]` entry:

```toml
  "jinja2>=3.1",
```

- [ ] **Step 2: Install**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: installs `jinja2` (if not already present), no errors.

- [ ] **Step 3: Create package + config**

Create `src/aishelf/site/__init__.py`:

```python
"""Display site (M-display): renders contract content as a video + blog site."""
```

Create `src/aishelf/site/config.py`:

```python
"""Where the display site reads collected content from."""

from __future__ import annotations

import os
from pathlib import Path


def get_data_dir() -> Path:
    """Directory holding `videos/` and `blogs/` record files."""
    return Path(os.environ.get("AISHELF_DATA_DIR", "data"))
```

- [ ] **Step 4: Verify import**

Run: `.venv/bin/python -c "import jinja2; from aishelf.site.config import get_data_dir; print(get_data_dir())"`
Expected: prints `data`, no ImportError.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/aishelf/site/__init__.py src/aishelf/site/config.py
git commit -m "build(site): add jinja2 dep and data-dir config"
```

---

## Task 2: View functions

**Files:**
- Create: `src/aishelf/site/views.py`
- Test: `tests/unit/test_site_views.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_views.py`:

```python
from pathlib import Path

from aishelf.contract.loader import load_items
from aishelf.site import views

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"
ITEMS = load_items(FIXTURES)  # sorted desc: blog-ddd, youtube-aaa, blog-ccc, bilibili-bbb


def _ids(items):
    return [it.id for it in items]


def test_videos_and_blogs_split_preserves_order():
    assert _ids(views.videos(ITEMS)) == ["youtube-aaa", "bilibili-bbb"]
    assert _ids(views.blogs(ITEMS)) == ["blog-ddd", "blog-ccc"]


def test_search_matches_title_summary_and_keyword_case_insensitive():
    assert _ids(views.search(ITEMS, "march")) == ["youtube-aaa"]      # title/summary
    assert _ids(views.search(ITEMS, "MARCH")) == ["youtube-aaa"]      # case-insensitive
    assert _ids(views.search(ITEMS, "agents")) == ["blog-ddd"]        # keyword hit
    assert views.search(ITEMS, "zzz") == []                           # miss
    assert views.search(ITEMS, "") == []                             # empty query


def test_by_keyword_exact_keyword_entry():
    assert _ids(views.by_keyword(ITEMS, "ai")) == ["youtube-aaa"]
    assert _ids(views.by_keyword(ITEMS, "research")) == ["blog-ccc"]
    assert views.by_keyword(ITEMS, "nope") == []


def test_author_key_and_grouping():
    yt = next(it for it in ITEMS if it.id == "youtube-aaa")
    assert views.author_key(yt) == "Author One"  # no author_id -> author name
    assert _ids(views.by_author(ITEMS, "Writer Two")) == ["blog-ddd"]


def test_paginate_pages_and_clamp():
    p1 = views.paginate(ITEMS, page=1, per_page=2)
    assert _ids(p1.items) == ["blog-ddd", "youtube-aaa"]
    assert (p1.total, p1.total_pages, p1.has_prev, p1.has_next) == (4, 2, False, True)

    p2 = views.paginate(ITEMS, page=2, per_page=2)
    assert _ids(p2.items) == ["blog-ccc", "bilibili-bbb"]
    assert (p2.has_prev, p2.has_next) == (True, False)

    clamped = views.paginate(ITEMS, page=99, per_page=2)
    assert clamped.page == 2  # clamped to last page

    empty = views.paginate([], page=1, per_page=2)
    assert empty.items == [] and empty.total == 0 and empty.total_pages == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_views.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aishelf.site.views'`.

- [ ] **Step 3: Implement views**

Create `src/aishelf/site/views.py`:

```python
"""Pure view logic over a list of ContentItem records (no HTTP)."""

from __future__ import annotations

from dataclasses import dataclass

from aishelf.contract.models import ContentItem


@dataclass
class Page:
    items: list[ContentItem]
    page: int
    per_page: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.per_page <= 0:
            return 1
        return max(1, (self.total + self.per_page - 1) // self.per_page)

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


def videos(items: list[ContentItem]) -> list[ContentItem]:
    return [it for it in items if it.type == "video"]


def blogs(items: list[ContentItem]) -> list[ContentItem]:
    return [it for it in items if it.type == "blog"]


def search(items: list[ContentItem], q: str) -> list[ContentItem]:
    needle = (q or "").strip().lower()
    if not needle:
        return []
    out = []
    for it in items:
        haystack = [it.title, it.summary, *it.keywords]
        if any(needle in (s or "").lower() for s in haystack):
            out.append(it)
    return out


def by_keyword(items: list[ContentItem], kw: str) -> list[ContentItem]:
    needle = (kw or "").strip().lower()
    if not needle:
        return list(items)
    return [it for it in items if any(needle == k.lower() for k in it.keywords)]


def author_key(item: ContentItem) -> str:
    return getattr(item, "author_id", None) or item.author


def by_author(items: list[ContentItem], key: str) -> list[ContentItem]:
    return [it for it in items if author_key(it) == key]


def paginate(items: list[ContentItem], page: int, per_page: int) -> Page:
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page) if per_page > 0 else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return Page(items=items[start : start + per_page], page=page, per_page=per_page, total=total)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_views.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/views.py tests/unit/test_site_views.py
git commit -m "feat(site): add pure view functions (split/search/keyword/author/paginate)"
```

---

## Task 3: FastAPI app, templates, and route tests

**Files:**
- Create: `src/aishelf/site/app.py`
- Create: the 13 templates and `static/style.css` (below)
- Test: `tests/unit/test_site_app.py`

- [ ] **Step 1: Write the failing route tests**

Create `tests/unit/test_site_app.py`:

```python
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(FIXTURES))
    from aishelf.site.app import app
    return TestClient(app)


def test_home_lists_latest(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "March talk" in r.text       # a video
    assert "May post" in r.text         # a blog


def test_videos_section(client):
    r = client.get("/videos")
    assert r.status_code == 200
    assert "March talk" in r.text and "January talk" in r.text


def test_blogs_section(client):
    r = client.get("/blogs")
    assert r.status_code == 200
    assert "May post" in r.text and "February post" in r.text


def test_video_detail(client):
    r = client.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert "March talk" in r.text
    assert "去原站观看" in r.text       # no embed_url -> link fallback


def test_blog_detail(client):
    r = client.get("/blogs/blog-ccc")
    assert r.status_code == 200
    assert "February post" in r.text and "Example Blog" in r.text


def test_unknown_id_renders_404(client):
    r = client.get("/videos/does-not-exist")
    assert r.status_code == 404
    assert "404" in r.text


def test_author_page(client):
    r = client.get(f"/authors/{quote('Writer Two')}")
    assert r.status_code == 200
    assert "May post" in r.text


def test_search(client):
    r = client.get("/search", params={"q": "march"})
    assert r.status_code == 200
    assert "March talk" in r.text


def test_keyword_filter(client):
    r = client.get("/videos", params={"keyword": "ai"})
    assert r.status_code == 200
    assert "March talk" in r.text and "January talk" not in r.text


def test_empty_data_dir_shows_empty_state(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    from aishelf.site.app import app
    c = TestClient(app)
    r = c.get("/videos")
    assert r.status_code == 200
    assert "暂无内容" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aishelf.site.app'`.

- [ ] **Step 3: Implement the app**

Create `src/aishelf/site/app.py`:

```python
"""FastAPI app for the display site: server-rendered video + blog pages."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aishelf.contract.loader import load_items
from aishelf.site import views
from aishelf.site.config import get_data_dir

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

VIDEOS_PER_PAGE = 24
BLOGS_PER_PAGE = 20
SEARCH_PER_PAGE = 20
HOME_PREVIEW = 8


def _fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"


templates.env.filters["duration"] = _fmt_duration

app = FastAPI(title="aishelf")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _items():
    return load_items(get_data_dir())


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse("not_found.html", {"request": request}, status_code=404)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    items = _items()
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "videos": views.videos(items)[:HOME_PREVIEW],
            "blogs": views.blogs(items)[:HOME_PREVIEW],
        },
    )


@app.get("/videos", response_class=HTMLResponse)
def videos_page(request: Request, page: int = 1, keyword: str = "", q: str = ""):
    items = _items()
    if q:
        result = views.videos(views.search(items, q))
    elif keyword:
        result = views.by_keyword(views.videos(items), keyword)
    else:
        result = views.videos(items)
    return templates.TemplateResponse(
        "videos.html",
        {"request": request, "page": views.paginate(result, page, VIDEOS_PER_PAGE), "keyword": keyword, "q": q},
    )


@app.get("/blogs", response_class=HTMLResponse)
def blogs_page(request: Request, page: int = 1, keyword: str = "", q: str = ""):
    items = _items()
    if q:
        result = views.blogs(views.search(items, q))
    elif keyword:
        result = views.by_keyword(views.blogs(items), keyword)
    else:
        result = views.blogs(items)
    return templates.TemplateResponse(
        "blogs.html",
        {"request": request, "page": views.paginate(result, page, BLOGS_PER_PAGE), "keyword": keyword, "q": q},
    )


@app.get("/videos/{item_id}", response_class=HTMLResponse)
def video_detail(request: Request, item_id: str):
    item = next((it for it in views.videos(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "video_detail.html", {"request": request, "item": item, "section_url": "/videos"}
    )


@app.get("/blogs/{item_id}", response_class=HTMLResponse)
def blog_detail(request: Request, item_id: str):
    item = next((it for it in views.blogs(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "blog_detail.html", {"request": request, "item": item, "section_url": "/blogs"}
    )


@app.get("/authors/{key}", response_class=HTMLResponse)
def author_page(request: Request, key: str):
    mine = views.by_author(_items(), key)
    if not mine:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        "author.html",
        {"request": request, "key": key, "videos": views.videos(mine), "blogs": views.blogs(mine)},
    )


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", page: int = 1):
    results = views.search(_items(), q)
    page_obj = views.paginate(results, page, SEARCH_PER_PAGE)
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "q": q,
            "page": page_obj,
            "videos": views.videos(page_obj.items),
            "blogs": views.blogs(page_obj.items),
        },
    )
```

Note: FastAPI resolves the literal routes `/videos` and `/videos/{item_id}` unambiguously (a bare `/videos` never matches the `{item_id}` route), so ordering is not a concern. `{key}` in the author route receives the URL-decoded value automatically.

- [ ] **Step 4: Create the templates**

Create `src/aishelf/site/templates/base.html`:

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{% block title %}aishelf{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/">aishelf</a>
    <nav><a href="/videos">视频</a><a href="/blogs">博客</a></nav>
    <form class="search" action="/search" method="get">
      <input name="q" placeholder="搜索标题/摘要/关键词" value="{{ q|default('') }}" />
      <button type="submit">搜索</button>
    </form>
  </header>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

Create `src/aishelf/site/templates/_video_card.html`:

```html
<a class="card" href="/videos/{{ it.id }}">
  <span class="thumb"><img src="{{ it.thumbnail_url }}" alt="" loading="lazy" />
    {% if it.duration_seconds %}<span class="dur">{{ it.duration_seconds|duration }}</span>{% endif %}
  </span>
  <span class="title">{{ it.title }}</span>
  <span class="sub">{{ it.author }} · {{ it.published_at[:10] }}</span>
</a>
```

Create `src/aishelf/site/templates/_blog_row.html`:

```html
<li class="blogrow">
  {% if it.cover_image_url %}<img class="cover" src="{{ it.cover_image_url }}" alt="" loading="lazy" />{% endif %}
  <div class="blogtext">
    <a class="title" href="/blogs/{{ it.id }}">{{ it.title }}</a>
    <div class="sub">{{ it.author }} · {{ it.published_at[:10] }}{% if it.site_name %} · {{ it.site_name }}{% endif %}</div>
    <p class="summary">{{ it.summary }}</p>
  </div>
</li>
```

Create `src/aishelf/site/templates/_pager.html`:

```html
{% if page.total_pages > 1 %}
<nav class="pager">
  {% if page.has_prev %}<a href="?page={{ page.page - 1 }}{% if keyword %}&keyword={{ keyword|urlencode }}{% endif %}{% if q %}&q={{ q|urlencode }}{% endif %}">上一页</a>{% endif %}
  <span>{{ page.page }} / {{ page.total_pages }}</span>
  {% if page.has_next %}<a href="?page={{ page.page + 1 }}{% if keyword %}&keyword={{ keyword|urlencode }}{% endif %}{% if q %}&q={{ q|urlencode }}{% endif %}">下一页</a>{% endif %}
</nav>
{% endif %}
```

Create `src/aishelf/site/templates/_keywords.html`:

```html
{% if item.keywords %}
<div class="keywords">
  {% for kw in item.keywords %}<a href="{{ section_url }}?keyword={{ kw|urlencode }}">{{ kw }}</a>{% endfor %}
</div>
{% endif %}
```

Create `src/aishelf/site/templates/home.html`:

```html
{% extends "base.html" %}
{% block content %}
<section>
  <h2>最新视频 <a class="more" href="/videos">更多 →</a></h2>
  {% if videos %}<div class="grid">{% for it in videos %}{% include "_video_card.html" %}{% endfor %}</div>
  {% else %}<p class="empty">暂无内容</p>{% endif %}
</section>
<section>
  <h2>最新博客 <a class="more" href="/blogs">更多 →</a></h2>
  {% if blogs %}<ul class="bloglist">{% for it in blogs %}{% include "_blog_row.html" %}{% endfor %}</ul>
  {% else %}<p class="empty">暂无内容</p>{% endif %}
</section>
{% endblock %}
```

Create `src/aishelf/site/templates/videos.html`:

```html
{% extends "base.html" %}
{% block title %}视频 · aishelf{% endblock %}
{% block content %}
<h1>视频{% if keyword %} · 关键词「{{ keyword }}」{% endif %}{% if q %} · 搜索「{{ q }}」{% endif %}</h1>
{% if page.total == 0 %}<p class="empty">暂无内容</p>
{% else %}<div class="grid">{% for it in page.items %}{% include "_video_card.html" %}{% endfor %}</div>
{% include "_pager.html" %}{% endif %}
{% endblock %}
```

Create `src/aishelf/site/templates/blogs.html`:

```html
{% extends "base.html" %}
{% block title %}博客 · aishelf{% endblock %}
{% block content %}
<h1>博客{% if keyword %} · 关键词「{{ keyword }}」{% endif %}{% if q %} · 搜索「{{ q }}」{% endif %}</h1>
{% if page.total == 0 %}<p class="empty">暂无内容</p>
{% else %}<ul class="bloglist">{% for it in page.items %}{% include "_blog_row.html" %}{% endfor %}</ul>
{% include "_pager.html" %}{% endif %}
{% endblock %}
```

Create `src/aishelf/site/templates/video_detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ item.title }} · aishelf{% endblock %}
{% block content %}
<article class="detail">
  <h1>{{ item.title }}</h1>
  <div class="sub"><a href="/authors/{{ (item.author_id or item.author)|urlencode }}">{{ item.author }}</a> · {{ item.published_at[:10] }} · {{ item.platform }}</div>
  {% if item.embed_url %}
  <div class="player"><iframe src="{{ item.embed_url }}" frameborder="0" allowfullscreen></iframe></div>
  {% else %}
  <a class="poster" href="{{ item.source_url }}" target="_blank" rel="noopener"><img src="{{ item.thumbnail_url }}" alt="" /></a>
  <p><a class="btn" href="{{ item.source_url }}" target="_blank" rel="noopener">去原站观看 →</a></p>
  {% endif %}
  <p class="summary">{{ item.summary }}</p>
  {% include "_keywords.html" %}
</article>
{% endblock %}
```

Create `src/aishelf/site/templates/blog_detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ item.title }} · aishelf{% endblock %}
{% block content %}
<article class="detail">
  {% if item.cover_image_url %}<img class="cover-lg" src="{{ item.cover_image_url }}" alt="" />{% endif %}
  <h1>{{ item.title }}</h1>
  <div class="sub"><a href="/authors/{{ (item.author_id or item.author)|urlencode }}">{{ item.author }}</a> · {{ item.published_at[:10] }}{% if item.site_name %} · {{ item.site_name }}{% endif %}</div>
  <p class="summary">{{ item.summary }}</p>
  <p><a class="btn" href="{{ item.source_url }}" target="_blank" rel="noopener">阅读全文(原站) →</a></p>
  {% include "_keywords.html" %}
</article>
{% endblock %}
```

Create `src/aishelf/site/templates/author.html`:

```html
{% extends "base.html" %}
{% block title %}{{ key }} · aishelf{% endblock %}
{% block content %}
<h1>{{ key }}</h1>
{% if videos %}<h2>视频</h2><div class="grid">{% for it in videos %}{% include "_video_card.html" %}{% endfor %}</div>{% endif %}
{% if blogs %}<h2>博客</h2><ul class="bloglist">{% for it in blogs %}{% include "_blog_row.html" %}{% endfor %}</ul>{% endif %}
{% endblock %}
```

Create `src/aishelf/site/templates/search.html`:

```html
{% extends "base.html" %}
{% block title %}搜索「{{ q }}」· aishelf{% endblock %}
{% block content %}
<h1>搜索「{{ q }}」</h1>
{% if page.total == 0 %}<p class="empty">没有匹配的内容</p>
{% else %}
{% if videos %}<h2>视频</h2><div class="grid">{% for it in videos %}{% include "_video_card.html" %}{% endfor %}</div>{% endif %}
{% if blogs %}<h2>博客</h2><ul class="bloglist">{% for it in blogs %}{% include "_blog_row.html" %}{% endfor %}</ul>{% endif %}
{% include "_pager.html" %}{% endif %}
{% endblock %}
```

Create `src/aishelf/site/templates/not_found.html`:

```html
{% extends "base.html" %}
{% block title %}404 · aishelf{% endblock %}
{% block content %}
<div class="empty"><h1>404</h1><p>没找到这个内容。<a href="/">回首页</a></p></div>
{% endblock %}
```

- [ ] **Step 5: Create the stylesheet**

Create `src/aishelf/site/static/style.css`:

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "PingFang SC", sans-serif; color: #1f2933; background: #f5f5f7; }
a { color: inherit; text-decoration: none; }
.topbar { display: flex; align-items: center; gap: 20px; padding: 12px 20px; background: #1f2933; color: #fff; position: sticky; top: 0; }
.topbar .brand { font-weight: 700; font-size: 18px; }
.topbar nav a { margin-right: 14px; color: #cbd2d9; }
.topbar nav a:hover { color: #fff; }
.topbar .search { margin-left: auto; display: flex; gap: 6px; }
.topbar .search input { padding: 7px 10px; border: none; border-radius: 8px; width: 240px; }
.topbar .search button { padding: 7px 14px; border: none; border-radius: 8px; background: #0a84ff; color: #fff; cursor: pointer; }
main { max-width: 1100px; margin: 0 auto; padding: 20px; }
h1 { font-size: 22px; } h2 { font-size: 17px; margin-top: 28px; } .more { font-size: 13px; color: #0a84ff; }
.empty { color: #7b8794; padding: 40px 0; text-align: center; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
.card { display: flex; flex-direction: column; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.card .thumb { position: relative; display: block; aspect-ratio: 16/9; background: #e4e7eb; }
.card .thumb img { width: 100%; height: 100%; object-fit: cover; }
.card .dur { position: absolute; right: 6px; bottom: 6px; background: rgba(0,0,0,.75); color: #fff; font-size: 12px; padding: 1px 5px; border-radius: 4px; }
.card .title { padding: 8px 10px 0; font-weight: 600; font-size: 14px; }
.card .sub { padding: 2px 10px 10px; color: #7b8794; font-size: 12px; }
.bloglist { list-style: none; padding: 0; margin: 0; }
.blogrow { display: flex; gap: 14px; padding: 14px 0; border-bottom: 1px solid #e4e7eb; }
.blogrow .cover { width: 140px; height: 90px; object-fit: cover; border-radius: 8px; flex: none; }
.blogrow .title { font-weight: 600; font-size: 16px; }
.blogrow .sub { color: #7b8794; font-size: 13px; margin: 3px 0; }
.blogrow .summary { margin: 4px 0 0; color: #3e4c59; font-size: 14px; }
.detail { background: #fff; padding: 20px; border-radius: 12px; }
.detail .sub { color: #7b8794; margin: 6px 0 14px; }
.detail .player iframe { width: 100%; aspect-ratio: 16/9; border-radius: 10px; }
.detail .poster img, .detail .cover-lg { width: 100%; max-height: 420px; object-fit: cover; border-radius: 10px; }
.detail .summary { line-height: 1.6; }
.btn { display: inline-block; padding: 8px 16px; background: #0a84ff; color: #fff; border-radius: 8px; }
.keywords { margin-top: 14px; display: flex; flex-wrap: wrap; gap: 8px; }
.keywords a { background: #e4e7eb; padding: 3px 10px; border-radius: 999px; font-size: 13px; }
.pager { display: flex; gap: 14px; align-items: center; justify-content: center; margin: 24px 0; }
.pager a { color: #0a84ff; }
```

- [ ] **Step 6: Run the route tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_app.py -v`
Expected: PASS (10 passed).

- [ ] **Step 7: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates src/aishelf/site/static tests/unit/test_site_app.py
git commit -m "feat(site): add FastAPI routes, templates, and styles"
```

---

## Task 4: Launcher

**Files:**
- Create: `src/aishelf/site/__main__.py`

- [ ] **Step 1: Create the launcher**

Create `src/aishelf/site/__main__.py`:

```python
"""Launch the display site: python -m aishelf.site"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("AISHELF_SITE_HOST", "127.0.0.1")
    port = int(os.environ.get("AISHELF_SITE_PORT", "8001"))
    uvicorn.run("aishelf.site.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the app imports through the launcher path**

Run: `.venv/bin/python -c "from aishelf.site.app import app; print(type(app).__name__)"`
Expected: prints `FastAPI`.

- [ ] **Step 3: Commit**

```bash
git add src/aishelf/site/__main__.py
git commit -m "feat(site): add python -m aishelf.site launcher"
```

---

## Task 5: Full-suite verification + manual run

**Files:** none (verification only)

- [ ] **Step 1: Run the whole default suite**

Run: `.venv/bin/pytest -q`
Expected: all tests pass (webui + contract + site), network deselected.

- [ ] **Step 2: Start the site against the fixtures and smoke it**

Run (background): `AISHELF_DATA_DIR=tests/fixtures/contract AISHELF_SITE_PORT=8001 .venv/bin/python -m aishelf.site`
Then: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/` and `curl -s http://127.0.0.1:8001/videos | grep -c "March talk"`
Expected: `200`, and the grep count is `1`. Stop the server afterward.

---

## Self-Review Notes

- **Spec coverage:** home (Task 3), videos/blogs sections with keyword+search+pagination (Task 3 routes + Task 2 views), video/blog detail incl. embed-or-link (Task 3 templates), author page (Task 3), search grouped by type (Task 3), 404 + empty state (Task 3 handler/tests), `python -m aishelf.site` (Task 4), `AISHELF_DATA_DIR` config (Task 1), jinja2 dep (Task 1). Defaults (24/20/20 per page, 8 preview) live in `app.py` constants.
- **Type/name consistency:** `views.videos/blogs/search/by_keyword/by_author/author_key/paginate` and `Page.{items,page,per_page,total,total_pages,has_prev,has_next}` are referenced identically in `app.py`, templates, and tests. `author_key` (used in `by_author`) and the template's `(item.author_id or item.author)` produce the same key, so author links resolve to existing author pages. `section_url` is passed for both detail templates and consumed by `_keywords.html`.
- **Placeholder scan:** every code/template/CSS step is complete; no TBD/TODO.
- **Empty/undefined safety:** `_pager.html` and `base.html` reference `keyword`/`q` with `{% if %}`/`|default('')`; Jinja's default Undefined is falsy, so search/detail pages that don't pass `keyword` render without error.

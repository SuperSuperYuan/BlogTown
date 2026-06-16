# 自写 Markdown 博客 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user write original blog posts in markdown, stored locally and rendered inline, merged into the existing `/blogs` list with an "原创" badge — collected items unchanged.

**Architecture:** Self-authored posts are ordinary `BlogItem` JSON records in `data/blogs/<id>.json` with two new fields: `body` (markdown source) and `origin` (`"collected"` | `"self"`). They flow through the existing loader → `/blogs` list, DB sync → search/graph, and delete — all reused. A new `site/posts.py` does atomic writes (the `notes.py` pattern); a new `site/markdown.py` renders + sanitizes markdown server-side; the `/blogs/{id}` detail route branches on `origin`. Live preview calls the same server renderer so preview is byte-identical to the published output.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, Pydantic v2, `markdown-it-py` (render), `nh3` (sanitize), `python-multipart` (form POST), pytest.

---

## File Structure

- **Modify** `pyproject.toml` — add `markdown-it-py`, `nh3`, `python-multipart` deps.
- **Modify** `src/aishelf/contract/models.py` — add `body` + `origin` to `BlogItem`.
- **Create** `src/aishelf/site/markdown.py` — `render_markdown(text) -> str` (render + sanitize, never raises).
- **Create** `src/aishelf/site/posts.py` — `create_post`, `read_post`, `update_post`, `_summarize` (atomic writes).
- **Modify** `src/aishelf/site/config.py` — `blog_author()` reading `ATLAS_BLOG_AUTHOR`.
- **Modify** `src/aishelf/site/app.py` — routes `GET /write`, `GET /write/{id}`, `POST /posts`, `POST /posts/{id}`, `POST /posts/preview`; branch `blog_detail` on `origin`.
- **Create** `src/aishelf/site/templates/write.html` — editor (left) + live preview (right).
- **Modify** `src/aishelf/site/templates/blog_detail.html` — branch on `item.origin`.
- **Modify** `src/aishelf/site/templates/_blog_row.html` — "原创" badge for self posts.
- **Modify** `src/aishelf/site/templates/base.html` — top-nav "写博客" link.
- **Modify** `src/aishelf/site/static/style.css` — badge + write-page styles.
- **Create** tests: `test_contract_models` additions, `test_site_markdown.py`, `test_site_posts.py`, `test_site_posts_routes.py`, `test_site_app.py` additions.

**Convention note:** Following the `notes.py` pattern, `posts.py` does pure atomic writes and the **route** triggers the off-thread `db sync` (via the existing `_sync_db_async` helper in `app.py`). `posts.py` never imports `app`.

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml:10-21`

- [ ] **Step 1: Add the three runtime deps**

In `pyproject.toml`, add to the `dependencies` list (after `"numpy>=1.26",`):

```toml
  "markdown-it-py>=3.0",
  "nh3>=0.2",
  "python-multipart>=0.0.9",
```

- [ ] **Step 2: Install**

Run: `pip install -e ".[dev]"`
Expected: installs `markdown-it-py`, `nh3`, `python-multipart` without error.

- [ ] **Step 3: Verify imports**

Run: `python -c "import markdown_it, nh3, multipart; print('ok')"`
Expected: prints `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add markdown-it-py, nh3, python-multipart deps"
```

---

## Task 2: Extend the BlogItem model

**Files:**
- Modify: `src/aishelf/contract/models.py:39-43`
- Test: `tests/unit/test_contract_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_contract_models.py`:

```python
def test_blog_defaults_origin_collected_and_body_none():
    item = parse_item(BLOG)  # BLOG fixture has neither field
    assert isinstance(item, BlogItem)
    assert item.origin == "collected"
    assert item.body is None


def test_blog_accepts_self_origin_and_body():
    raw = {**BLOG, "origin": "self", "body": "# Hello\n\nworld"}
    item = parse_item(raw)
    assert item.origin == "self"
    assert item.body == "# Hello\n\nworld"


def test_blog_rejects_unknown_origin():
    with pytest.raises(ValidationError):
        parse_item({**BLOG, "origin": "draft"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/test_contract_models.py -k "origin or body" -v`
Expected: FAIL — `origin`/`body` attributes do not exist yet.

- [ ] **Step 3: Add the fields**

In `src/aishelf/contract/models.py`, change `BlogItem` to:

```python
class BlogItem(ContentItem):
    type: Literal["blog"] = "blog"
    cover_image_url: str | None = None
    site_name: str | None = None
    author_id: str | None = None
    body: str | None = None                       # markdown source; self-authored only
    origin: Literal["collected", "self"] = "collected"
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/unit/test_contract_models.py -v`
Expected: PASS (all model tests, old + new).

- [ ] **Step 5: Re-export the JSON Schema (Hermes contract)**

Run: `python -m aishelf.contract.schema`
Then: `git diff --stat docs/contract/content-item.schema.json`
Expected: the schema file updates to include the new optional `body`/`origin` properties.

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/contract/models.py tests/unit/test_contract_models.py docs/contract/content-item.schema.json
git commit -m "feat(contract): add body + origin fields to BlogItem"
```

---

## Task 3: Markdown render + sanitize module

**Files:**
- Create: `src/aishelf/site/markdown.py`
- Test: `tests/unit/test_site_markdown.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_markdown.py`:

```python
from aishelf.site.markdown import render_markdown


def test_renders_basic_markdown():
    html = render_markdown("# Title\n\nsome **bold** text")
    assert "<h1>" in html and "Title" in html
    assert "<strong>bold</strong>" in html


def test_strips_script_tags():
    html = render_markdown("hi\n\n<script>alert(1)</script>")
    assert "<script" not in html
    assert "alert(1)" not in html or "<script" not in html  # script element gone


def test_strips_inline_event_handlers_and_js_urls():
    html = render_markdown('<a href="javascript:alert(1)" onclick="x()">click</a>')
    assert "javascript:" not in html
    assert "onclick" not in html


def test_empty_input_returns_empty_string():
    assert render_markdown("") == ""


def test_renderer_failure_falls_back_to_escaped_text(monkeypatch):
    import aishelf.site.markdown as m

    def boom(_text):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(m, "_render", boom)
    html = render_markdown("<b>raw</b> & stuff")
    # falls back to escaped plain text, never raises
    assert "&lt;b&gt;" in html and "&amp;" in html
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/test_site_markdown.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the module**

Create `src/aishelf/site/markdown.py`:

```python
"""Render user-authored markdown to sanitized HTML for inline display.

The author is the only trusted local user, so sanitizing is cheap defense in
depth (strip <script>, inline event handlers, javascript: URLs). Rendering
never raises: on any failure it falls back to escaped plain text so a page
can't be crashed by malformed input.
"""

from __future__ import annotations

import html
import logging

import nh3
from markdown_it import MarkdownIt

logger = logging.getLogger(__name__)

_MD = MarkdownIt("commonmark", {"linkify": True})


def _render(text: str) -> str:
    """Markdown -> raw HTML (may contain anything the source asked for)."""
    return _MD.render(text)


def render_markdown(text: str) -> str:
    """Render markdown to sanitized HTML; '' for empty, escaped text on error."""
    if not text:
        return ""
    try:
        raw = _render(text)
        return nh3.clean(raw)
    except Exception as exc:  # never let a bad post crash the page
        logger.warning("markdown render failed, falling back to plain text: %s", exc)
        return html.escape(text)
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/unit/test_site_markdown.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/markdown.py tests/unit/test_site_markdown.py
git commit -m "feat(site): markdown render + sanitize module"
```

---

## Task 4: Config — default blog author

**Files:**
- Modify: `src/aishelf/site/config.py`
- Test: `tests/unit/test_site_posts.py` (created in Task 5; this step only adds the function)

- [ ] **Step 1: Add `blog_author()`**

Append to `src/aishelf/site/config.py`:

```python
def blog_author() -> str:
    """Default author name stamped on self-authored posts."""
    return os.environ.get("ATLAS_BLOG_AUTHOR", "我")
```

- [ ] **Step 2: Verify it imports**

Run: `python -c "from aishelf.site.config import blog_author; print(blog_author())"`
Expected: prints `我`

- [ ] **Step 3: Commit**

```bash
git add src/aishelf/site/config.py
git commit -m "feat(site): ATLAS_BLOG_AUTHOR config for self-authored posts"
```

---

## Task 5: Posts persistence module

**Files:**
- Create: `src/aishelf/site/posts.py`
- Test: `tests/unit/test_site_posts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_posts.py`:

```python
import json
from pathlib import Path

import pytest

from aishelf.contract.models import BlogItem
from aishelf.site import posts


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ATLAS_BLOG_AUTHOR", "测试作者")
    return tmp_path


def _read_json(data_dir, item_id):
    return json.loads((data_dir / "blogs" / f"{item_id}.json").read_text(encoding="utf-8"))


def test_create_post_writes_self_blog_record(data_dir):
    item = posts.create_post("我的标题", "# 正文\n\n这是一段内容。")
    assert isinstance(item, BlogItem)
    assert item.id.startswith("post-")
    assert item.origin == "self"
    assert item.type == "blog"
    assert item.author == "测试作者"
    assert item.title == "我的标题"
    assert item.body == "# 正文\n\n这是一段内容。"
    assert item.keywords == []
    assert item.platform == "atlas"
    assert item.source_url == ""
    # persisted to disk with the same id as the filename stem
    on_disk = _read_json(data_dir, item.id)
    assert on_disk["origin"] == "self"
    assert on_disk["body"] == "# 正文\n\n这是一段内容。"


def test_summary_is_auto_extracted_from_body(data_dir):
    item = posts.create_post("t", "# 大标题\n\n**重点**内容在这里，更多文字跟随其后。")
    assert "大标题" in item.summary or "重点" in item.summary
    assert "#" not in item.summary and "*" not in item.summary
    assert len(item.summary) <= 121  # ~120 char cap


def test_create_post_id_is_path_safe_and_stable_per_clock(data_dir):
    item = posts.create_post("标题", "body", now=lambda: "2026-06-16T12:00:00")
    # safe_id charset; deterministic given fixed title+timestamp
    from aishelf.site.items import safe_id
    assert safe_id(item.id) == item.id


def test_read_post_returns_none_for_missing(data_dir):
    assert posts.read_post("post-does-not-exist") is None


def test_read_post_returns_none_for_collected_record(data_dir):
    # write a collected blog directly
    blogs = data_dir / "blogs"
    blogs.mkdir(parents=True)
    (blogs / "blog-x.json").write_text(json.dumps({
        "id": "blog-x", "type": "blog", "title": "c", "author": "a",
        "platform": "p", "source_url": "https://e/x", "published_at": "2024-01-01",
        "summary": "s", "keywords": [], "collected_at": "2024-01-02T00:00:00",
    }), encoding="utf-8")
    assert posts.read_post("blog-x") is None  # origin != self


def test_update_post_preserves_published_at_and_updates_fields(data_dir):
    created = posts.create_post("旧标题", "旧正文", now=lambda: "2026-01-01T00:00:00")
    original_published = created.published_at
    updated = posts.update_post(created.id, "新标题", "# 新正文\n\n新的内容")
    assert updated.title == "新标题"
    assert updated.body == "# 新正文\n\n新的内容"
    assert updated.published_at == original_published  # unchanged on edit
    assert "新" in updated.summary


def test_update_post_rejects_unknown_id(data_dir):
    with pytest.raises(LookupError):
        posts.update_post("post-nope", "t", "b")


def test_update_post_rejects_collected_record(data_dir):
    blogs = data_dir / "blogs"
    blogs.mkdir(parents=True)
    (blogs / "blog-y.json").write_text(json.dumps({
        "id": "blog-y", "type": "blog", "title": "c", "author": "a",
        "platform": "p", "source_url": "https://e/y", "published_at": "2024-01-01",
        "summary": "s", "keywords": [], "collected_at": "2024-01-02T00:00:00",
    }), encoding="utf-8")
    with pytest.raises(LookupError):
        posts.update_post("blog-y", "t", "b")
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/test_site_posts.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the module**

Create `src/aishelf/site/posts.py`:

```python
"""Create, read, and update self-authored blog posts.

A post is an ordinary BlogItem JSON record in data/blogs/<id>.json with
origin="self" and a markdown `body`. Writes are atomic (.tmp + os.replace),
mirroring notes.py. This module performs pure persistence — the route layer
triggers the off-thread DB re-sync (same split as save_note).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from aishelf.contract.models import BlogItem
from aishelf.site.config import blog_author, get_data_dir
from aishelf.site.items import safe_id

SUMMARY_LEN = 120


def blogs_dir() -> Path:
    return get_data_dir() / "blogs"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# Strip the common inline markdown markers so the auto-summary reads as prose.
_MD_NOISE = re.compile(r"[#>*_`~\[\]()!-]+")


def _summarize(body: str, limit: int = SUMMARY_LEN) -> str:
    """First ~`limit` chars of `body` with markdown markers/whitespace stripped."""
    text = _MD_NOISE.sub(" ", body or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _new_id(title: str, timestamp: str) -> str:
    digest = hashlib.sha1((title + timestamp).encode("utf-8")).hexdigest()[:12]
    return safe_id(f"post-{digest}")


def _write(item: BlogItem) -> None:
    """Atomic write of a BlogItem to data/blogs/<id>.json."""
    directory = blogs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{item.id}.json"
    payload = item.model_dump(mode="json")
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f"{item.id}.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, final)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def create_post(title: str, body: str, now=_now) -> BlogItem:
    """Create a self-authored post, persist it, and return the record."""
    timestamp = now()
    item = BlogItem(
        id=_new_id(title, timestamp),
        title=title,
        author=blog_author(),
        platform="atlas",
        source_url="",
        published_at=timestamp,
        collected_at=timestamp,
        summary=_summarize(body),
        keywords=[],
        body=body,
        origin="self",
    )
    _write(item)
    return item


def read_post(item_id: str) -> BlogItem | None:
    """Load a self-authored post by id, or None if missing/not self/unreadable."""
    try:
        safe_id(item_id)
    except ValueError:
        return None
    path = blogs_dir() / f"{item_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        item = BlogItem(**data)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
        return None
    return item if item.origin == "self" else None


def update_post(item_id: str, title: str, body: str) -> BlogItem:
    """Update an existing self-authored post, preserving published_at.

    Raises LookupError if no self-authored post with that id exists.
    """
    existing = read_post(item_id)
    if existing is None:
        raise LookupError(item_id)
    updated = existing.model_copy(update={
        "title": title,
        "body": body,
        "summary": _summarize(body),
    })
    _write(updated)
    return updated
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/unit/test_site_posts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/posts.py tests/unit/test_site_posts.py
git commit -m "feat(site): posts.py create/read/update self-authored blogs"
```

---

## Task 6: Routes (write page, create, update, preview, detail branch)

**Files:**
- Modify: `src/aishelf/site/app.py`
- Test: `tests/unit/test_site_posts_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_posts_routes.py`:

```python
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)  # writable copy so posts can be created
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    monkeypatch.setenv("ATLAS_BLOG_AUTHOR", "我")
    from aishelf.site.app import app
    return TestClient(app)


def test_write_page_renders_empty_form(client):
    r = client.get("/write")
    assert r.status_code == 200
    assert 'name="title"' in r.text and 'name="body"' in r.text


def test_create_post_redirects_to_detail(client):
    r = client.post("/posts", data={"title": "原创文章", "body": "# 标题\n\n内容"},
                     follow_redirects=False)
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/blogs/post-")
    # the redirect target renders the inline body + 原创 badge
    detail = client.get(location)
    assert detail.status_code == 200
    assert "原创" in detail.text
    assert "阅读全文" not in detail.text  # source-site button hidden for self posts


def test_create_post_empty_title_does_not_write(client):
    r = client.post("/posts", data={"title": "  ", "body": "内容"},
                    follow_redirects=False)
    assert r.status_code == 400
    # nothing new in /blogs
    blogs = client.get("/blogs")
    assert "post-" not in blogs.text


def test_write_edit_page_prefills_self_post(client):
    created = client.post("/posts", data={"title": "可编辑", "body": "原始正文"},
                          follow_redirects=False)
    item_id = created.headers["location"].rsplit("/", 1)[-1]
    r = client.get(f"/write/{item_id}")
    assert r.status_code == 200
    assert "可编辑" in r.text and "原始正文" in r.text


def test_write_edit_page_404_for_collected(client):
    r = client.get("/write/blog-ccc")  # a collected fixture blog
    assert r.status_code == 404


def test_update_post_changes_body_and_keeps_published(client):
    created = client.post("/posts", data={"title": "t1", "body": "b1"},
                          follow_redirects=False)
    item_id = created.headers["location"].rsplit("/", 1)[-1]
    r = client.post(f"/posts/{item_id}", data={"title": "t2", "body": "# 改了"},
                    follow_redirects=False)
    assert r.status_code == 303
    detail = client.get(f"/blogs/{item_id}")
    assert "改了" in detail.text


def test_update_post_404_for_collected(client):
    r = client.post("/posts/blog-ccc", data={"title": "x", "body": "y"},
                    follow_redirects=False)
    assert r.status_code == 404


def test_preview_returns_sanitized_html(client):
    r = client.post("/posts/preview", json={"body": "# 预览\n\n<script>x</script>"})
    assert r.status_code == 200
    html = r.json()["html"]
    assert "<h1>" in html
    assert "<script" not in html


def test_collected_blog_detail_unchanged(client):
    r = client.get("/blogs/blog-ccc")
    assert r.status_code == 200
    assert "阅读全文" in r.text  # collected items keep the source-site button
    assert "原创" not in r.text
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/test_site_posts_routes.py -v`
Expected: FAIL — routes not defined / 404s.

- [ ] **Step 3: Wire imports and the blog_detail branch**

In `src/aishelf/site/app.py`, add `markdown` and `posts` to the `aishelf.site` import block (lines 25-37):

```python
from aishelf.site import (
    allowlist,
    ask,
    collect,
    hermes,
    items,
    llm,
    markdown,
    notes,
    posts,
    schedule_state,
    scheduler,
    schedules,
    views,
)
```

Add this import near the top (after the FastAPI imports, ~line 9):

```python
from fastapi import Form
from fastapi.responses import RedirectResponse
```

(Merge `Form` into the existing `from fastapi import ...` line and `RedirectResponse` into the existing `from fastapi.responses import ...` line rather than duplicating.)

Replace the `blog_detail` route (lines 187-196) with a version that branches on `origin`:

```python
@app.get("/blogs/{item_id}", response_class=HTMLResponse)
def blog_detail(request: Request, item_id: str):
    item = next((it for it in views.blogs(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    body_html = (
        markdown.render_markdown(item.body or "")
        if getattr(item, "origin", "collected") == "self"
        else None
    )
    return templates.TemplateResponse(
        request,
        "blog_detail.html",
        {"item": item, "section_url": "/blogs", "note": _note_for(item),
         "body_html": body_html},
    )
```

- [ ] **Step 4: Add the write/create/update/preview routes**

In `src/aishelf/site/app.py`, after the `blog_detail` route, add:

```python
@app.get("/write", response_class=HTMLResponse)
def write_new_page(request: Request):
    return templates.TemplateResponse(request, "write.html", {"item": None})


@app.get("/write/{item_id}", response_class=HTMLResponse)
def write_edit_page(request: Request, item_id: str):
    item = posts.read_post(item_id)
    if item is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "write.html", {"item": item})


@app.post("/posts")
def create_post_route(request: Request, title: str = Form(""), body: str = Form("")):
    if not title.strip() or not body.strip():
        return templates.TemplateResponse(
            request, "write.html",
            {"item": None, "error": "标题和正文都不能为空", "title": title, "body": body},
            status_code=400,
        )
    item = posts.create_post(title.strip(), body)
    _sync_db_async(get_data_dir())  # make it searchable / graphed off-thread
    return RedirectResponse(f"/blogs/{item.id}", status_code=303)


@app.post("/posts/{item_id}")
def update_post_route(request: Request, item_id: str, title: str = Form(""), body: str = Form("")):
    if not title.strip() or not body.strip():
        existing = posts.read_post(item_id)
        if existing is None:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request, "write.html",
            {"item": existing, "error": "标题和正文都不能为空", "title": title, "body": body},
            status_code=400,
        )
    try:
        item = posts.update_post(item_id, title.strip(), body)
    except LookupError:
        raise HTTPException(status_code=404)
    _sync_db_async(get_data_dir())
    return RedirectResponse(f"/blogs/{item.id}", status_code=303)


class _PreviewRequest(BaseModel):
    body: str = Field(default="", max_length=200_000)


@app.post("/posts/preview")
def preview_post(req: _PreviewRequest):
    # Same server-side renderer as the published page → byte-identical preview.
    return {"html": markdown.render_markdown(req.body)}
```

- [ ] **Step 5: Run to verify they pass (templates land in Task 7 — expect template errors only)**

Run: `pytest tests/unit/test_site_posts_routes.py -v`
Expected: route logic resolves, but tests asserting rendered HTML may fail until `write.html` exists and `blog_detail.html` branches. The non-template assertions (redirect status, 404s, preview JSON) should PASS now. Proceed to Task 7, then re-run.

- [ ] **Step 6: Commit**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_posts_routes.py
git commit -m "feat(site): write/create/update/preview routes + origin-branched blog detail"
```

---

## Task 7: Templates and styles

**Files:**
- Create: `src/aishelf/site/templates/write.html`
- Modify: `src/aishelf/site/templates/blog_detail.html`
- Modify: `src/aishelf/site/templates/_blog_row.html`
- Modify: `src/aishelf/site/templates/base.html`
- Modify: `src/aishelf/site/static/style.css`

- [ ] **Step 1: Add the top-nav link**

In `src/aishelf/site/templates/base.html:12`, add a "写博客" link to the `<nav>` (after the 博客 link):

```html
<nav><a href="/videos">视频</a><a href="/blogs">博客</a><a href="/write">写博客</a><a href="/ask">问答</a><a href="/graph">图谱</a><a href="/collect">Hermes</a></nav>
```

- [ ] **Step 2: Branch the blog detail template**

Replace the body of `src/aishelf/site/templates/blog_detail.html` with:

```html
{% extends "base.html" %}
{% block title %}{{ item.title }} · Atlas{% endblock %}
{% block content %}
<article class="detail">
  {% if item.origin == "self" %}
  <h1>{{ item.title }} <span class="badge-origin">原创</span></h1>
  <div class="sub"><a href="/authors/{{ (item.author_id or item.author)|urlencode }}">{{ item.author }}</a> · {{ item.published_at[:10] }}</div>
  <p><a class="btn" href="/write/{{ item.id }}">编辑 →</a></p>
  <div class="post-body">{{ body_html|safe }}</div>
  {% else %}
  {% if item.cover_image_url %}<img class="cover-lg" src="{{ item.cover_image_url|safe_url }}" alt="" />{% endif %}
  <h1>{{ item.title }}</h1>
  <div class="sub"><a href="/authors/{{ (item.author_id or item.author)|urlencode }}">{{ item.author }}</a> · {{ item.published_at[:10] }}{% if item.site_name %} · {{ item.site_name }}{% endif %}</div>
  <p class="summary">{{ item.summary }}</p>
  <p><a class="btn" href="{{ item.source_url|safe_url }}" target="_blank" rel="noopener noreferrer">阅读全文(原站) →</a></p>
  {% endif %}
  {% include "_keywords.html" %}
  {% include "_note_editor.html" %}
  {% include "_delete_button.html" %}
</article>
{% endblock %}
```

- [ ] **Step 3: Add the "原创" badge to blog rows**

In `src/aishelf/site/templates/_blog_row.html`, change the title line (line 4) to append the badge for self posts:

```html
    <a class="title" href="/blogs/{{ it.id }}">{{ it.title }}</a>{% if it.origin == "self" %} <span class="badge-origin">原创</span>{% endif %}
```

- [ ] **Step 4: Create the write/edit page**

Create `src/aishelf/site/templates/write.html`:

```html
{% extends "base.html" %}
{% block title %}{% if item %}编辑{% else %}写博客{% endif %} · Atlas{% endblock %}
{% block content %}
<h1>{% if item %}编辑文章{% else %}写新文章{% endif %}</h1>
{% if error %}<p class="note-status err">{{ error }}</p>{% endif %}
<form class="write-form" method="post" action="{% if item %}/posts/{{ item.id }}{% else %}/posts{% endif %}">
  <input class="write-title" name="title" placeholder="标题"
         value="{{ title if title is defined else (item.title if item else '') }}" />
  <div class="write-split">
    <textarea id="md-body" class="write-body" name="body"
              placeholder="用 markdown 写正文…">{{ body if body is defined else (item.body if item else '') }}</textarea>
    <div id="md-preview" class="post-body write-preview"></div>
  </div>
  <button class="btn" type="submit">发布</button>
</form>
<script>
(function () {
  const ta = document.getElementById("md-body");
  const preview = document.getElementById("md-preview");
  let timer = null;
  async function render() {
    try {
      const r = await fetch("/posts/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: ta.value }),
      });
      const data = await r.json();
      preview.innerHTML = data.html;  // server-sanitized HTML
    } catch (e) { /* preview is best-effort */ }
  }
  ta.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(render, 250);  // debounce
  });
  render();  // initial paint (prefilled edit)
})();
</script>
{% endblock %}
```

- [ ] **Step 5: Add styles**

Append to `src/aishelf/site/static/style.css`:

```css
.badge-origin { font-size: .7em; background: #2563eb; color: #fff; border-radius: 4px; padding: 1px 6px; vertical-align: middle; }
.write-form { display: flex; flex-direction: column; gap: 12px; }
.write-title { font-size: 1.2em; padding: 8px; }
.write-split { display: flex; gap: 16px; align-items: stretch; }
.write-body, .write-preview { flex: 1; min-height: 60vh; }
.write-body { padding: 10px; font-family: ui-monospace, monospace; resize: vertical; }
.write-preview { padding: 10px; border: 1px solid #ddd; border-radius: 6px; overflow: auto; }
.post-body img { max-width: 100%; }
```

- [ ] **Step 6: Run the full posts-route suite**

Run: `pytest tests/unit/test_site_posts_routes.py -v`
Expected: PASS (all template + redirect + 404 + preview assertions).

- [ ] **Step 7: Commit**

```bash
git add src/aishelf/site/templates/ src/aishelf/site/static/style.css
git commit -m "feat(site): write page, origin-branched detail, 原创 badge + styles"
```

---

## Task 8: Integration — list mixing + full sync flow

**Files:**
- Test: `tests/unit/test_site_app.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_site_app.py` a writable-copy fixture and tests. (The existing module-level `client` fixture points at the read-only FIXTURES dir; add a separate writable client.)

```python
import shutil


@pytest.fixture
def rw_client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    monkeypatch.setenv("ATLAS_BLOG_AUTHOR", "我")
    from aishelf.site.app import app
    return TestClient(app)


def test_self_post_appears_in_blogs_list_with_badge(rw_client):
    rw_client.post("/posts", data={"title": "我的原创长文", "body": "正文内容"},
                   follow_redirects=False)
    r = rw_client.get("/blogs")
    assert r.status_code == 200
    assert "我的原创长文" in r.text   # mixed with collected blogs
    assert "原创" in r.text          # badge present
    assert "May post" in r.text       # collected blogs still listed


def test_self_post_is_searchable_after_create(rw_client):
    # creating a post triggers an off-thread sync; force a synchronous sync so
    # the assertion is deterministic in the test (no sleeping on a daemon thread)
    from aishelf.db import sync as db_sync
    from aishelf.db.config import default_db_path
    import os
    data_dir = os.environ["AISHELF_DATA_DIR"]
    rw_client.post("/posts", data={"title": "可检索原创", "body": "独特关键词xyzzy"},
                   follow_redirects=False)
    db_sync.sync(data_dir, default_db_path(data_dir))
    r = rw_client.get("/api/search", params={"q": "可检索原创"})
    assert any("可检索原创" in hit["title"] for hit in r.json()["results"])
```

- [ ] **Step 2: Run to verify they fail (or already pass)**

Run: `pytest tests/unit/test_site_app.py -k "self_post" -v`
Expected: PASS if Tasks 2-7 are complete (these exercise the wired-together feature). If any fail, fix the underlying task.

- [ ] **Step 3: Run the complete test suite**

Run: `pytest`
Expected: all tests PASS (network tests skipped by default).

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_site_app.py
git commit -m "test(site): self-authored posts in /blogs list + searchable after sync"
```

---

## Task 9: Docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md` (if it documents features/config)

- [ ] **Step 1: Document the new module + config in CLAUDE.md**

In `CLAUDE.md`, under the `aishelf/site/` bullet list, add `markdown.py` and `posts.py` descriptions; under **Config**, document `ATLAS_BLOG_AUTHOR` (default `我`). Add a sentence noting self-authored posts are `BlogItem`s with `origin="self"` + `body`, written by `posts.py` and rendered inline on the detail page.

- [ ] **Step 2: Update README if it lists features/config**

Run: `grep -n "ATLAS_CHAT\|/ask\|/graph" README.md | head`
If the README documents routes/config, add `/write` and `ATLAS_BLOG_AUTHOR` in the same style.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document self-authored markdown blogs (posts.py, markdown.py, ATLAS_BLOG_AUTHOR)"
```

---

## Self-Review

**Spec coverage:**
- 展示位置 / merge into `/blogs` + badge → Task 7 (`_blog_row` badge), Task 8 (list mixing test). ✓
- 极简编辑字段 (title + body; author/summary/keywords/time defaults) → Task 5 (`create_post`). ✓
- 发布后管理 (edit + delete, no draft) → Task 6 (`/write/{id}`, `/posts/{id}`), delete reuses existing `/delete/{id}` (no new code). ✓
- 开放访问 (no passcode) → Task 6 routes omit `_require_collect_token`. ✓
- 数据模型 `body`+`origin` → Task 2. ✓
- `posts.py` atomic write + off-thread sync → Task 5 (write) + Task 6 (route triggers `_sync_db_async`). ✓
- `markdown.py` render+sanitize, fallback → Task 3. ✓
- Routes table (`/write`, `/write/{id}`, `/posts`, `/posts/{id}`, `/posts/preview`) → Task 6. ✓
- Templates (base nav, write.html, blog_detail branch, _blog_row badge) → Task 7. ✓
- Live preview via server renderer (byte-identical) → Task 7 (`write.html` fetches `/posts/preview`). ✓
- `ATLAS_BLOG_AUTHOR` config → Task 4. ✓
- Error handling (empty fields no write, 404 for non-self/missing, render fallback) → Tasks 3, 5, 6. ✓
- Tests per spec → Tasks 2,3,5,6,8. ✓
- YAGNI exclusions (no drafts, no upload, no WYSIWYG, no passcode, no separate list) → honored; none implemented. ✓

**Deviations from spec (intentional, noted):**
- POST redirect uses **303 See Other** (correct POST→GET status) rather than the spec's "302"; semantically identical for browsers.
- Sync trigger lives in the **route**, not `posts.py` — matches the existing `save_note`/route split exactly (`posts.py` stays free of `app` imports).
- `/posts` + `/posts/{id}` accept **form-encoded** bodies (enables no-JS submit + 303 redirect, per route table); `/posts/preview` uses **JSON** (consistent with `notes`/`ask` fetch endpoints).

**Placeholder scan:** none — every code/step is concrete.

**Type consistency:** `create_post`/`read_post`/`update_post` signatures match between Task 5 definition and Task 6 callers; `render_markdown` signature matches between Task 3 and Task 6/7 usage; `body_html` context key matches between route (Task 6) and template (Task 7); `origin`/`body` field names match across model, posts, templates, tests.

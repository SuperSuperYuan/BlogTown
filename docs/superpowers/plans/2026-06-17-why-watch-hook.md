# 「一句话钩子」(Why-Watch Hook) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a one-line AI-generated "为什么值得看" hook beneath each item in browse/home/author lists, reusing the existing graph-alias LLM pipeline.

**Architecture:** The hook is a derived field stored in the SQLite `items` table, generated during `sync` exactly like the `alias` (same module, same batching, same regeneration policy). Browse pages render from contract files per-request, so a small read-only `hooks_for(db_path, ids)` bridges DB → template via a `{id: hook}` map. Unconfigured `ATLAS_CHAT_*` ⇒ no hooks ⇒ pages render unchanged.

**Tech Stack:** Python, FastAPI + Jinja2, SQLite (sqlite3), OpenAI-compatible chat client, pytest.

**Spec:** `docs/superpowers/specs/2026-06-17-why-watch-hook-design.md`

---

## File Structure

- `src/aishelf/alias.py` — add `generate_hooks`; refactor the shared LLM-call core out of `generate_aliases` (DRY). Both stay in this one "LLM short-string client" module.
- `src/aishelf/db/schema.py` — add `hook TEXT` column to `items`.
- `src/aishelf/db/sync.py` — generate/regenerate `hook` in the existing sync transaction.
- `src/aishelf/db/search.py` — add read-only `hooks_for(db_path, ids)`.
- `src/aishelf/site/app.py` — `_hooks_for(items)` helper; pass `hooks` to home/videos/blogs/author routes.
- `src/aishelf/site/templates/_video_card.html`, `_blog_row.html` — render the hook.
- `src/aishelf/site/static/style.css` — `.hook` styling.
- Tests: `tests/unit/test_alias.py`, `test_db_sync.py`, `test_db_search.py`, `test_site_app.py`.
- `CLAUDE.md` — document the new column/functions/routes.

---

## Task 1: `generate_hooks` in `alias.py` (DRY refactor + new function)

**Files:**
- Modify: `src/aishelf/alias.py`
- Test: `tests/unit/test_alias.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_alias.py`:

```python
def test_generate_hooks_not_configured_returns_none(monkeypatch):
    monkeypatch.delenv("ATLAS_CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("ATLAS_CHAT_MODEL", raising=False)
    assert alias.generate_hooks([("t", "s")]) is None


def test_generate_hooks_parses_json_array(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('["讲清楚了RAG为何失效", "手把手搭Agent"]'))
    out = alias.generate_hooks([("RAG paper", "x"), ("Agent guide", "y")])
    assert out == ["讲清楚了RAG为何失效", "手把手搭Agent"]


def test_generate_hooks_empty_input_returns_none(monkeypatch):
    _configure(monkeypatch)
    assert alias.generate_hooks([]) is None


def test_generate_hooks_wrong_length_returns_none(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('["仅一句"]'))
    assert alias.generate_hooks([("a", ""), ("b", "")]) is None


def test_generate_hooks_client_error_returns_none(monkeypatch):
    _configure(monkeypatch)

    def _boom(s):
        raise RuntimeError("down")

    monkeypatch.setattr(alias, "get_client", _boom)
    assert alias.generate_hooks([("a", "")]) is None


def test_generate_hooks_caps_length(monkeypatch):
    _configure(monkeypatch)
    long = "很" * 60
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient(f'["{long}"]'))
    out = alias.generate_hooks([("a", "")])
    assert len(out) == 1 and len(out[0]) <= alias.HOOK_MAX_CHARS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_alias.py -k hooks -v`
Expected: FAIL with `AttributeError: module 'aishelf.alias' has no attribute 'generate_hooks'`.

- [ ] **Step 3: Refactor the shared core and add `generate_hooks`**

In `src/aishelf/alias.py`:

(a) Generalize `_clean` to take a cap, and add the hook prompt + constant near the top (after `_PROMPT`):

```python
HOOK_MAX_CHARS = 40  # safety cap; the prompt asks for <= 30 Chinese chars

_HOOK_PROMPT = (
    "为下列每条内容各写一句话，说明它为什么值得一看（不超过30个汉字），"
    "要具体、有信息量、能勾起兴趣，不要空话套话。只返回一个 JSON 字符串数组，"
    "元素顺序与输入编号一致，不要输出任何额外文字或解释。\n\n"
)
```

Change `_clean` from:

```python
def _clean(a: str) -> str:
    return (a or "").strip().strip('"「」""').strip()[:ALIAS_MAX_CHARS]
```

to:

```python
def _clean(a: str, cap: int = ALIAS_MAX_CHARS) -> str:
    return (a or "").strip().strip('"「」""').strip()[:cap]
```

(b) Replace the body of `generate_aliases` with a delegation, and add a private core + `generate_hooks`. Replace the whole existing `generate_aliases` function with:

```python
def _generate_strings(prompt: str, pairs: list[tuple[str, str]], cap: int) -> list[str] | None:
    """Batched LLM call returning one cleaned string per (title, summary) pair,
    or None if unconfigured / empty / on any error or parse mismatch. Each batch
    must return a JSON array of the same length (all-or-nothing)."""
    s = get_alias_settings()
    if s is None or not pairs:
        return None
    try:
        client = get_client(s)
        out: list[str] = []
        for i in range(0, len(pairs), ALIAS_BATCH_SIZE):
            chunk = pairs[i:i + ALIAS_BATCH_SIZE]
            listing = "\n".join(
                f"{n + 1}. {title} ｜ {(summary or '')[:80]}"
                for n, (title, summary) in enumerate(chunk)
            )
            resp = client.chat.completions.create(
                model=s["model"],
                messages=[{"role": "user", "content": prompt + listing}],
                stream=False,
            )
            content = resp.choices[0].message.content or ""
            arr = json.loads(_extract_json_array(content))
            if not isinstance(arr, list) or len(arr) != len(chunk):
                return None
            out.extend(_clean(str(x), cap) for x in arr)
        return out
    except Exception as exc:  # degrade to caller fallback, never crash sync
        logger.warning("string generation failed: %s", exc)
        return None


def generate_aliases(pairs: list[tuple[str, str]]) -> list[str] | None:
    """≤8-char graph-node aliases for (title, summary) pairs (see _generate_strings)."""
    return _generate_strings(_PROMPT, pairs, ALIAS_MAX_CHARS)


def generate_hooks(pairs: list[tuple[str, str]]) -> list[str] | None:
    """One-sentence "why watch" hooks (≤30 chars) for (title, summary) pairs."""
    return _generate_strings(_HOOK_PROMPT, pairs, HOOK_MAX_CHARS)
```

- [ ] **Step 4: Run the full alias test file to verify all pass**

Run: `pytest tests/unit/test_alias.py -v`
Expected: PASS — both the pre-existing alias tests (unchanged behavior after refactor) and the new hook tests.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/alias.py tests/unit/test_alias.py
git commit -m "feat(alias): generate_hooks (一句话钩子) via shared LLM core"
```

---

## Task 2: Add `hook` column to the DB schema

**Files:**
- Modify: `src/aishelf/db/schema.py:34` (after the `alias TEXT,` line)

- [ ] **Step 1: Add the column**

In `src/aishelf/db/schema.py`, change:

```python
  alias             TEXT,
  content_hash  TEXT NOT NULL,
```

to:

```python
  alias             TEXT,
  hook              TEXT,
  content_hash  TEXT NOT NULL,
```

- [ ] **Step 2: Verify a fresh DB has the column**

Run: `python -c "from aishelf.db import schema; c=schema.connect(':memory:'); schema.init_db(c); print([r[1] for r in c.execute('PRAGMA table_info(items)')])"`
Expected: the printed column list includes `'hook'`.

- [ ] **Step 3: Commit**

```bash
git add src/aishelf/db/schema.py
git commit -m "feat(db): add hook column to items"
```

---

## Task 3: Generate/regenerate `hook` during sync

**Files:**
- Modify: `src/aishelf/db/sync.py`
- Test: `tests/unit/test_db_sync.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_db_sync.py` (reuses the module's existing `_write_video` and `_alias`/`embed` imports):

```python
# ---------------------------------------------------------------------------
# Hook tests (一句话钩子)
# ---------------------------------------------------------------------------

def _hook_of(db_path, vid):
    con = schema.connect(db_path)
    row = con.execute("SELECT hook FROM items WHERE id=?", (vid,)).fetchone()
    con.close()
    return row["hook"]


def test_sync_stores_hook_for_new_item(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)
    monkeypatch.setattr(_alias, "generate_hooks", lambda pairs: ["为什么值得看"] * len(pairs))
    sync(data, db)
    assert _hook_of(db, "v1") == "为什么值得看"


def test_sync_skips_hook_when_unconfigured(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: False)
    sync(data, db)
    assert _hook_of(db, "v1") is None


def test_sync_regenerates_hook_on_title_change_not_note(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)
    calls = {"n": 0}

    def _gen(pairs):
        calls["n"] += 1
        return [f"钩子{calls['n']}"] * len(pairs)

    monkeypatch.setattr(_alias, "generate_hooks", _gen)
    sync(data, db)
    assert calls["n"] == 1 and _hook_of(db, "v1") == "钩子1"

    # note-only change: hook must NOT regenerate
    (data / "notes").mkdir(exist_ok=True)
    (data / "notes" / "v1.json").write_text(
        json.dumps({"id": "v1", "text": "新笔记", "updated_at": "2024-02-01"}, ensure_ascii=False),
        encoding="utf-8")
    sync(data, db)
    assert calls["n"] == 1 and _hook_of(db, "v1") == "钩子1"

    # title change: hook regenerates
    rec = json.loads((data / "videos" / "v1.json").read_text(encoding="utf-8"))
    rec["title"] = "全新的标题"
    (data / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    sync(data, db)
    assert calls["n"] == 2 and _hook_of(db, "v1") == "钩子2"


def test_sync_backfills_missing_hook_without_title_change(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _write_video(data, "v1")
    db = tmp_path / "atlas.db"
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: True)
    monkeypatch.setattr(_alias, "generate_aliases", lambda pairs: None)
    monkeypatch.setattr(_alias, "generate_hooks", lambda pairs: None)  # first sync: gen fails
    sync(data, db)
    assert _hook_of(db, "v1") is None
    # same title, generation now works -> hook backfilled
    monkeypatch.setattr(_alias, "generate_hooks", lambda pairs: ["补的钩子"] * len(pairs))
    sync(data, db)
    assert _hook_of(db, "v1") == "补的钩子"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_db_sync.py -k hook -v`
Expected: FAIL — hooks are never generated yet, so `_hook_of` returns `None` where a value is asserted (e.g. `test_sync_stores_hook_for_new_item`).

- [ ] **Step 3: Implement hook generation in sync**

In `src/aishelf/db/sync.py`:

(a) Extend the `existing` fetch (currently lines ~88–96) to include `has_hook`:

```python
        existing = {
            r["id"]: (r["content_hash"], r["embedding_model"], r["has_emb"],
                      r["title"], r["has_alias"], r["has_hook"])
            for r in con.execute(
                "SELECT id, content_hash, embedding_model, "
                "(embedding IS NOT NULL) AS has_emb, title, "
                "(alias IS NOT NULL AND alias != '') AS has_alias, "
                "(hook IS NOT NULL AND hook != '') AS has_hook FROM items"
            )
        }
```

(b) Declare the collector alongside `to_alias` (currently ~line 101):

```python
        to_alias: list = []               # items needing a (re)generated alias
        to_hook: list = []                # items needing a (re)generated hook
```

(c) In the per-item loop, after the `needs_alias = ...` block, add:

```python
            needs_hook = alias.is_configured() and (
                prev is None or it.title != prev[3] or not prev[5]
            )
```

(d) Update the short-circuit (currently `if not needs_index and not needs_emb and not needs_alias:`):

```python
            if not needs_index and not needs_emb and not needs_alias and not needs_hook:
                summary.unchanged += 1
                continue
```

(e) After the existing `if needs_alias: to_alias.append(it)` line, add:

```python
            if needs_hook:
                to_hook.append(it)
```

(f) After the existing alias-generation block (the `if to_alias:` block, ~lines 166–175), add:

```python
        if to_hook:
            new_hooks = alias.generate_hooks([(it.title, it.summary) for it in to_hook])
            if new_hooks and len(new_hooks) == len(to_hook):
                for it, hk in zip(to_hook, new_hooks):
                    con.execute("UPDATE items SET hook=? WHERE id=?", (hk, it.id))
            elif new_hooks:
                logger.warning(
                    "generate_hooks returned %d for %d items; skipping hook update",
                    len(new_hooks), len(to_hook),
                )
```

- [ ] **Step 4: Run the full sync test file to verify all pass**

Run: `pytest tests/unit/test_db_sync.py -v`
Expected: PASS — new hook tests pass and all pre-existing sync/alias/embedding/edge tests still pass (the new hook path is a no-op when `generate_hooks` returns `None`, which it does when `ATLAS_CHAT_*` is unset, so the existing alias tests are unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/sync.py tests/unit/test_db_sync.py
git commit -m "feat(db): generate per-item hook during sync (title-keyed, like alias)"
```

---

## Task 4: `hooks_for(db_path, ids)` read helper

**Files:**
- Modify: `src/aishelf/db/search.py`
- Test: `tests/unit/test_db_search.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_db_search.py` (reuses the module's `_write`, `sync`, `schema`):

```python
from aishelf.db.search import hooks_for


def _set_hook(db_path, vid, hook):
    con = schema.connect(db_path)
    con.execute("UPDATE items SET hook=? WHERE id=?", (hook, vid))
    con.commit()
    con.close()


def test_hooks_for_returns_map(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1", "标题一")
    _write(data, "blogs", "b1", "标题二")
    sync(data, db)
    _set_hook(db, "v1", "钩子一")
    _set_hook(db, "b1", "钩子二")
    assert hooks_for(db, ["v1", "b1"]) == {"v1": "钩子一", "b1": "钩子二"}


def test_hooks_for_skips_empty_and_missing(tmp_path):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write(data, "videos", "v1", "标题一")
    _write(data, "videos", "v2", "标题二")
    sync(data, db)
    _set_hook(db, "v1", "有钩子")
    _set_hook(db, "v2", "")  # empty hook -> omitted
    assert hooks_for(db, ["v1", "v2", "nope"]) == {"v1": "有钩子"}


def test_hooks_for_empty_ids_returns_empty(tmp_path):
    db = tmp_path / "atlas.db"
    assert hooks_for(db, []) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_db_search.py -k hooks_for -v`
Expected: FAIL with `ImportError: cannot import name 'hooks_for'`.

- [ ] **Step 3: Implement `hooks_for`**

In `src/aishelf/db/search.py`, add `import sqlite3` to the imports, then append:

```python
def hooks_for(db_path, ids: list[str]) -> dict[str, str]:
    """Map of {id: hook} for ids with a non-empty hook (others omitted).
    Returns {} for empty input or an unopenable/old DB — the hook is a derived
    nicety and must never be fatal to a page render."""
    if not ids:
        return {}
    try:
        con = schema.connect(db_path)
        try:
            schema.init_db(con)
            placeholders = ",".join("?" for _ in ids)
            rows = con.execute(
                f"SELECT id, hook FROM items WHERE id IN ({placeholders}) "
                "AND hook IS NOT NULL AND hook != ''",
                list(ids),
            ).fetchall()
            return {r["id"]: r["hook"] for r in rows}
        finally:
            con.close()
    except sqlite3.Error:
        return {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_db_search.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/db/search.py tests/unit/test_db_search.py
git commit -m "feat(db): hooks_for read helper (id -> hook map)"
```

---

## Task 5: Wire hooks into the site (routes + templates + style)

**Files:**
- Modify: `src/aishelf/site/app.py` (helper + home/videos/blogs/author routes)
- Modify: `src/aishelf/site/templates/_video_card.html`, `_blog_row.html`
- Modify: `src/aishelf/site/static/style.css`
- Test: `tests/unit/test_site_app.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_site_app.py`:

```python
import json as _json

from fastapi.testclient import TestClient


def _seed_hook_site(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    rec = {"id": "v1", "type": "video", "title": "大语言模型", "author": "作者甲",
           "platform": "youtube", "source_url": "https://x/v1",
           "published_at": "2024-01-01", "summary": "摘要", "keywords": [],
           "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}
    (tmp_path / "videos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "videos" / "v1.json").write_text(_json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    from aishelf.db.sync import sync
    from aishelf.db import schema
    sync(tmp_path, tmp_path / "atlas.db")
    con = schema.connect(tmp_path / "atlas.db")
    con.execute("UPDATE items SET hook=? WHERE id=?", ("一眼说清为什么值得看", "v1"))
    con.commit()
    con.close()


def test_videos_page_shows_hook(tmp_path, monkeypatch):
    _seed_hook_site(tmp_path, monkeypatch)
    from aishelf.site.app import app
    client = TestClient(app)
    r = client.get("/videos")
    assert r.status_code == 200
    assert "一眼说清为什么值得看" in r.text


def test_videos_page_renders_without_hook(tmp_path, monkeypatch):
    # No hook set -> page still renders fine (hook is optional).
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    rec = {"id": "v1", "type": "video", "title": "无钩子视频", "author": "作者甲",
           "platform": "youtube", "source_url": "https://x/v1",
           "published_at": "2024-01-01", "summary": "摘要", "keywords": [],
           "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}
    (tmp_path / "videos").mkdir(parents=True, exist_ok=True)
    (tmp_path / "videos" / "v1.json").write_text(_json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    from aishelf.site.app import app
    client = TestClient(app)
    r = client.get("/videos")
    assert r.status_code == 200
    assert "无钩子视频" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_site_app.py -k hook -v`
Expected: `test_videos_page_shows_hook` FAILs (hook text not in the rendered HTML because routes don't pass `hooks` and the template doesn't render it). `test_videos_page_renders_without_hook` may already pass — that's fine.

- [ ] **Step 3: Add the `_hooks_for` helper in `app.py`**

In `src/aishelf/site/app.py`, after `_note_for` (around line 92), add:

```python
def _hooks_for(items):
    """Map {id: hook} for the given items, tolerating a missing/locked derived
    DB (the hook is a derived nicety — never break a page render)."""
    try:
        return db_search.hooks_for(
            default_db_path(get_data_dir()), [it.id for it in items]
        )
    except Exception:  # derived view; never fatal
        return {}
```

- [ ] **Step 4: Pass `hooks` from the four browse routes**

In `src/aishelf/site/app.py`:

Replace the `home` route body (lines ~132–142) with:

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

Replace the `videos_page` return (lines ~154–158) with a named page object:

```python
    page_obj = views.paginate(result, page, VIDEOS_PER_PAGE)
    return templates.TemplateResponse(
        request,
        "videos.html",
        {"page": page_obj, "keyword": keyword, "q": q, "hooks": _hooks_for(page_obj.items)},
    )
```

Replace the `blogs_page` return (lines ~170–174) with:

```python
    page_obj = views.paginate(result, page, BLOGS_PER_PAGE)
    return templates.TemplateResponse(
        request,
        "blogs.html",
        {"page": page_obj, "keyword": keyword, "q": q, "hooks": _hooks_for(page_obj.items)},
    )
```

Replace the `author_page` return (lines ~267–271) with:

```python
    vids = views.videos(mine)
    blogs = views.blogs(mine)
    return templates.TemplateResponse(
        request,
        "author.html",
        {"key": key, "videos": vids, "blogs": blogs, "hooks": _hooks_for(vids + blogs)},
    )
```

- [ ] **Step 5: Render the hook in the partials**

In `src/aishelf/site/templates/_video_card.html`, add a hook line after the `sub` span (before the closing `</a>`):

```html
  <span class="sub">{{ it.author }} · {{ it.published_at[:10] }}</span>
  {% if hooks and hooks.get(it.id) %}<span class="hook">{{ hooks[it.id] }}</span>{% endif %}
```

In `src/aishelf/site/templates/_blog_row.html`, add the hook **above** the summary:

```html
    <div class="sub">{{ it.author }} · {{ it.published_at[:10] }}{% if it.site_name %} · {{ it.site_name }}{% endif %}</div>
    {% if hooks and hooks.get(it.id) %}<p class="hook">{{ hooks[it.id] }}</p>{% endif %}
    <p class="summary">{{ it.summary }}</p>
```

- [ ] **Step 6: Add `.hook` styling**

Append to `src/aishelf/site/static/style.css`:

```css
.hook { margin: 4px 0 0; padding-left: 8px; border-left: 3px solid #0a84ff; color: #52606d; font-size: 13px; line-height: 1.45; }
.card .hook { display: block; padding: 0 10px 8px; border-left: none; color: #0a6; font-size: 12px; }
.blogrow .hook { color: #1f2933; }
```

- [ ] **Step 7: Run the site tests to verify they pass**

Run: `pytest tests/unit/test_site_app.py -k hook -v`
Expected: PASS — `test_videos_page_shows_hook` now finds the hook text; `test_videos_page_renders_without_hook` still passes.

- [ ] **Step 8: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/_video_card.html src/aishelf/site/templates/_blog_row.html src/aishelf/site/static/style.css tests/unit/test_site_app.py
git commit -m "feat(site): show 一句话钩子 on browse/home/author lists"
```

---

## Task 6: Documentation + migration note

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

In the `aishelf/alias.py` bullet, note it now also exposes `generate_hooks` (one-sentence "why watch" hooks, ≤30 chars). In the `aishelf/db/` description, add `hook TEXT` to the list of nullable `items` columns (alongside `alias`), note `search.py` gains `hooks_for(db_path, ids)`, note `sync.py` also generates/regenerates a per-item `hook` (title-keyed like `alias`; note edits do NOT regenerate it), and that browse/home/author routes surface hooks via `_hooks_for`. In the **Derived DB** paragraph and the "Initial deployment" note, add that `sync --rebuild` backfills the `hook` column.

- [ ] **Step 2: Run the full test suite**

Run: `pytest`
Expected: PASS (all tests; network tests skipped by default).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document 一句话钩子 (hook column, generate_hooks, hooks_for)"
```

---

## Post-implementation: deploy migration

After merging, run once on the live instance to backfill hooks for existing items (requires `ATLAS_CHAT_*` configured):

```bash
python -m aishelf.db sync --rebuild
```

---

## Self-Review

- **Spec coverage:** generate_hooks (Task 1) ✓; `hook` column + rebuild backfill (Task 2, Task 6 migration) ✓; sync generation with title-keyed regeneration + note-edit exclusion + failure-tolerance (Task 3) ✓; `hooks_for` read bridge (Task 4) ✓; `_hooks_for` helper + home/videos/blogs/author wiring (Task 5) ✓; blog hook-above-summary + video card hook + `.hook` style + graceful no-hook render (Task 5) ✓; zero new config / degradation (covered by `generate_hooks`→None and `hooks and hooks.get` guards) ✓; docs (Task 6) ✓. Non-goals (no `/search`, no `/ask`, no detail page, no summary-only regen) are respected — no tasks add them.
- **Placeholder scan:** none — every code/test step has full code; every run step has an exact command + expected outcome.
- **Type consistency:** `generate_hooks(pairs) -> list[str]|None`, `hooks_for(db_path, ids) -> dict[str,str]`, `_hooks_for(items) -> dict`, `HOOK_MAX_CHARS`, `_generate_strings(prompt, pairs, cap)`, `_clean(a, cap=...)`, sync `prev` tuple index `prev[5]`=has_hook and `prev[3]`=title — all consistent across tasks and match the existing alias/`prev[4]` convention.

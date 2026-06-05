# Delete Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user delete a video/blog (record + its note) from the detail page.

**Architecture:** A new `items` module owns the canonical id validator and `delete_item` (unlinks the content record from videos/blogs plus the note). `notes.py` is refactored to reuse `items.safe_id`. The site gains `POST /delete/{id}`, and the detail pages get a confirm-guarded delete button that redirects to the section on success.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, pytest + `TestClient`.

**Spec:** `docs/superpowers/specs/2026-06-05-delete-items-design.md`

**Commands:** use `.venv/bin/python` / `.venv/bin/pytest`. Append to every commit body: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- Create: `src/aishelf/site/items.py` — `safe_id`, `delete_item`.
- Modify: `src/aishelf/site/notes.py` — use `items.safe_id`, drop the local `_safe_id`.
- Modify: `src/aishelf/site/app.py` — import `items`; add `POST /delete/{item_id}`.
- Create: `src/aishelf/site/templates/_delete_button.html` — delete button + JS.
- Modify: `src/aishelf/site/templates/video_detail.html`, `blog_detail.html` — include it.
- Modify: `src/aishelf/site/static/style.css` — `.btn-danger` + `.delete-bar`.
- Create: `tests/unit/test_site_items.py`, `tests/unit/test_site_delete_routes.py`.

---

## Task 1: items module + notes refactor

**Files:**
- Create: `src/aishelf/site/items.py`
- Modify: `src/aishelf/site/notes.py`
- Test: `tests/unit/test_site_items.py`

- [ ] **Step 1: Write the failing tests for items**

Create `tests/unit/test_site_items.py`:

```python
import json

import pytest

from aishelf.site import items


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    (tmp_path / "videos").mkdir()
    (tmp_path / "blogs").mkdir()
    (tmp_path / "notes").mkdir()
    return tmp_path


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_delete_removes_record_and_note(data_dir):
    rec = data_dir / "videos" / "youtube-x.json"
    note = data_dir / "notes" / "youtube-x.json"
    _write(rec, {"id": "youtube-x"})
    _write(note, {"id": "youtube-x", "text": "n"})
    assert items.delete_item("youtube-x") is True
    assert not rec.exists()
    assert not note.exists()


def test_delete_blog_record(data_dir):
    rec = data_dir / "blogs" / "blog-y.json"
    _write(rec, {"id": "blog-y"})
    assert items.delete_item("blog-y") is True
    assert not rec.exists()


def test_delete_unknown_returns_false(data_dir):
    assert items.delete_item("nope-z") is False


def test_delete_record_without_note_ok(data_dir):
    rec = data_dir / "videos" / "youtube-x.json"
    _write(rec, {"id": "youtube-x"})
    assert items.delete_item("youtube-x") is True  # missing note is not an error
    assert not rec.exists()


@pytest.mark.parametrize("bad", ["../etc", "a/b", "..", "x\\y", "", "a b", "a..b"])
def test_bad_id_rejected(data_dir, bad):
    with pytest.raises(ValueError):
        items.safe_id(bad)
    with pytest.raises(ValueError):
        items.delete_item(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_items.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aishelf.site.items'`.

- [ ] **Step 3: Implement items.py**

Create `src/aishelf/site/items.py`:

```python
"""Content items: id validation and deletion (record + note)."""

from __future__ import annotations

import re

from aishelf.site.config import get_data_dir

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_MODALITY_DIRS = ("videos", "blogs")


def safe_id(item_id: str) -> str:
    """Validate a content item id; raise ValueError on anything path-unsafe."""
    if not item_id or ".." in item_id or "/" in item_id or "\\" in item_id or not _SAFE_ID.match(item_id):
        raise ValueError(f"unsafe item id: {item_id!r}")
    return item_id


def delete_item(item_id: str) -> bool:
    """Delete the content record (video or blog) and its note.

    Returns True if a content record was removed, False if none existed.
    A missing note is not an error.
    """
    safe_id(item_id)
    base = get_data_dir()
    removed_record = False
    for sub in _MODALITY_DIRS:
        path = base / sub / f"{item_id}.json"
        if path.exists():
            path.unlink()
            removed_record = True
    (base / "notes" / f"{item_id}.json").unlink(missing_ok=True)
    return removed_record
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_items.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor notes.py to reuse items.safe_id**

In `src/aishelf/site/notes.py`: remove the `import re` line and the `_SAFE_ID` constant and the entire `_safe_id` function; add an import; and call `safe_id` instead of `_safe_id`.

Change the imports block from:

```python
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from aishelf.site.config import get_data_dir

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
```

to:

```python
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from aishelf.site.config import get_data_dir
from aishelf.site.items import safe_id

logger = logging.getLogger(__name__)
```

Delete this function entirely:

```python
def _safe_id(item_id: str) -> str:
    if not item_id or ".." in item_id or "/" in item_id or "\\" in item_id or not _SAFE_ID.match(item_id):
        raise ValueError(f"unsafe note id: {item_id!r}")
    return item_id
```

In `load_note`, change `_safe_id(item_id)` to `safe_id(item_id)`. In `save_note`, change `_safe_id(item_id)` to `safe_id(item_id)`.

- [ ] **Step 6: Verify notes tests still pass (regression)**

Run: `.venv/bin/pytest tests/unit/test_site_notes.py -v`
Expected: PASS (all still green — behavior unchanged).

- [ ] **Step 7: Commit**

```bash
git add src/aishelf/site/items.py src/aishelf/site/notes.py tests/unit/test_site_items.py
git commit -m "feat(site): add items module (safe_id + delete_item); reuse in notes"
```

---

## Task 2: Delete route, button, detail integration

**Files:**
- Modify: `src/aishelf/site/app.py`
- Create: `src/aishelf/site/templates/_delete_button.html`
- Modify: `src/aishelf/site/templates/video_detail.html`, `blog_detail.html`
- Modify: `src/aishelf/site/static/style.css`
- Test: `tests/unit/test_site_delete_routes.py`

- [ ] **Step 1: Write the failing route tests**

Create `tests/unit/test_site_delete_routes.py`:

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
    return TestClient(app), data


def test_delete_removes_record_and_note(client):
    c, data = client
    c.post("/notes/youtube-aaa", json={"text": "笔记"})
    assert (data / "notes" / "youtube-aaa.json").exists()
    r = c.post("/delete/youtube-aaa")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert not (data / "videos" / "youtube-aaa.json").exists()
    assert not (data / "notes" / "youtube-aaa.json").exists()
    assert c.get("/videos/youtube-aaa").status_code == 404


def test_delete_unknown_404(client):
    c, _ = client
    assert c.post("/delete/nope-zzz").status_code == 404


def test_delete_bad_id_400(client):
    c, _ = client
    assert c.post("/delete/a..b").status_code == 400


def test_detail_has_delete_button(client):
    c, _ = client
    r = c.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert 'id="delete-item"' in r.text and "删除" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_site_delete_routes.py -v`
Expected: FAIL — `POST /delete/...` 404 (route missing) / no delete button in detail.

- [ ] **Step 3: Add the delete route to app.py**

In `src/aishelf/site/app.py`, change the line `from aishelf.site import collect, hermes, notes, views` to add `items`:

```python
from aishelf.site import collect, hermes, items, notes, views
```

Append the route at the end of `src/aishelf/site/app.py`:

```python
@app.post("/delete/{item_id}")
def delete_item_route(item_id: str):
    try:
        removed = items.delete_item(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid id")
    if not removed:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}
```

- [ ] **Step 4: Create the delete-button partial**

Create `src/aishelf/site/templates/_delete_button.html`:

```html
<div class="delete-bar">
  <button id="delete-item" type="button" class="btn-danger">删除</button>
  <span id="delete-status" class="note-status"></span>
</div>
<script>
(function () {
  const btn = document.getElementById("delete-item");
  const status = document.getElementById("delete-status");
  btn.addEventListener("click", async () => {
    if (!confirm("确定删除这条内容及其笔记？此操作不可恢复")) return;
    btn.disabled = true;
    status.className = "note-status";
    status.textContent = "删除中…";
    try {
      const r = await fetch("/delete/{{ item.id }}", { method: "POST" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      window.location = "{{ section_url }}";
    } catch (e) {
      status.className = "note-status err";
      status.textContent = "删除失败：" + e;
      btn.disabled = false;
    }
  });
})();
</script>
```

- [ ] **Step 5: Include the partial in both detail templates**

In `src/aishelf/site/templates/video_detail.html`, add immediately before the closing `</article>` (after `{% include "_note_editor.html" %}`):

```html
  {% include "_delete_button.html" %}
```

Make the identical addition in `src/aishelf/site/templates/blog_detail.html` (before its closing `</article>`, after its `_note_editor.html` include).

- [ ] **Step 6: Add danger-button styles**

Append to `src/aishelf/site/static/style.css`:

```css
.delete-bar { display: flex; align-items: center; gap: 12px; margin-top: 22px; padding-top: 18px; border-top: 1px solid #e4e7eb; }
.btn-danger { background: #d64545; color: #fff; border: none; padding: 9px 18px; border-radius: 8px; font-size: 14px; cursor: pointer; }
.btn-danger:hover { background: #b91c1c; }
.btn-danger:disabled { opacity: .5; cursor: default; }
```

- [ ] **Step 7: Run the route tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_site_delete_routes.py -v`
Expected: PASS (4 passed).

- [ ] **Step 8: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/_delete_button.html src/aishelf/site/templates/video_detail.html src/aishelf/site/templates/blog_detail.html src/aishelf/site/static/style.css tests/unit/test_site_delete_routes.py
git commit -m "feat(site): add delete button + POST /delete/{id} on detail pages"
```

---

## Task 3: Full-suite verification + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the whole default suite**

Run: `.venv/bin/pytest -q`
Expected: all tests pass (contract + site + notes regression + items + delete), network deselected.

- [ ] **Step 2: Live smoke against a throwaway data dir**

Run (background): `AISHELF_DATA_DIR=/tmp/atlas_delete_demo AISHELF_SITE_PORT=8002 .venv/bin/python -m aishelf.site`
Then:
```
mkdir -p /tmp/atlas_delete_demo/videos
printf '{"id":"youtube-del","type":"video","title":"Del Me","author":"A","platform":"youtube","source_url":"https://y/del","published_at":"2024-01-01","summary":"s","keywords":[],"collected_at":"2024-01-01T00:00:00","thumbnail_url":"https://img/del.jpg"}' > /tmp/atlas_delete_demo/videos/youtube-del.json
curl -s -o /dev/null -w "before: %{http_code}\n" http://127.0.0.1:8002/videos/youtube-del
curl -s -X POST http://127.0.0.1:8002/delete/youtube-del
curl -s -o /dev/null -w "\nafter: %{http_code}\n" http://127.0.0.1:8002/videos/youtube-del
```
Expected: before `200`; the POST returns `{"ok":true}`; after `404`; and `/tmp/atlas_delete_demo/videos/youtube-del.json` is gone. Stop the server and remove `/tmp/atlas_delete_demo` afterward.

---

## Self-Review Notes

- **Spec coverage:** `safe_id` + `delete_item` (record from videos/blogs + note, returns bool) — Task 1; notes refactor to shared `safe_id` + regression — Task 1; `POST /delete/{id}` with 400 (bad id) / 404 (unknown) / `{ok:true}` — Task 2; confirm-guarded delete button redirecting to `section_url`, included in both detail templates — Task 2; `.btn-danger` style — Task 2; no blocklist / no batch (YAGNI) — honored. Verification + live smoke — Task 3.
- **Name/type consistency:** `items.safe_id` / `items.delete_item` used identically in app.py, notes.py, and tests; `delete_item` returns `bool` consumed by the route's `if not removed`. The partial posts to `/delete/{{ item.id }}` matching the `{item_id}` route param and redirects to `section_url` (already passed into both detail contexts).
- **No-cycle check:** `items` imports only `config`; `notes` imports `items`. No circular import.
- **Placeholder scan:** all code/template/CSS steps complete; no TBD.
- **Security:** every unlinked path is built from a `safe_id`-validated id; `..`/`/`/`\`/empty/out-of-charset → 400.

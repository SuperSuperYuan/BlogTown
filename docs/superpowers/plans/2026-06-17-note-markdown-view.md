# 笔记 Markdown 展示 + 重新编辑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the detail page, render a saved note as Markdown by default with an 「编辑」 toggle back to the textarea; saving re-renders in place without a page reload.

**Architecture:** A view⇄edit toggle in `_note_editor.html` driven by a few lines of vanilla JS. Markdown is rendered server-side with the existing `markdown.render_markdown` (sanitized via nh3) — both on initial load (detail route passes `note_html`) and on save (`POST /notes/{id}` returns the rendered `html`). Mirrors the existing self-authored-blog render path.

**Tech Stack:** FastAPI + Jinja2, `markdown-it-py` + `nh3` (already present), pytest.

**Spec:** `docs/superpowers/specs/2026-06-17-note-markdown-view-design.md`

---

## File Structure

- `src/aishelf/site/app.py` — `POST /notes/{item_id}` returns rendered `html`; `video_detail`/`blog_detail` pass `note_html`.
- `src/aishelf/site/templates/_note_editor.html` — view/edit blocks + toggle JS.
- `src/aishelf/site/static/style.css` — `.notes-head`, `.note-view`, `.btn-link`.
- Tests: `tests/unit/test_site_notes_routes.py`.
- `CLAUDE.md` — document the behavior.

---

## Task 1: `POST /notes/{item_id}` returns rendered HTML

**Files:**
- Modify: `src/aishelf/site/app.py` (the `save_note_route`)
- Test: `tests/unit/test_site_notes_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_site_notes_routes.py` (the `client` fixture already copies the contract fixtures into a writable data dir):

```python
def test_save_note_returns_rendered_html(client):
    r = client.post("/notes/youtube-aaa", json={"text": "**重点** 内容"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "updated_at" in body
    assert "<strong>重点</strong>" in body["html"]


def test_save_empty_note_returns_blank_html(client):
    r = client.post("/notes/youtube-aaa", json={"text": ""})
    assert r.status_code == 200
    assert r.json()["html"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_site_notes_routes.py -k "rendered_html or blank_html" -v`
Expected: FAIL with `KeyError: 'html'` (the response has no `html` field yet).

- [ ] **Step 3: Add `html` to the save response**

In `src/aishelf/site/app.py`, the current route is:

```python
@app.post("/notes/{item_id}")
def save_note_route(item_id: str, req: _NoteRequest):
    try:
        updated_at = notes.save_note(item_id, req.text)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid note id")
    # The note text feeds search; refresh the derived index off-thread.
    _sync_db_async(get_data_dir())
    return {"ok": True, "updated_at": updated_at}
```

Change the final `return` to include the rendered HTML:

```python
    _sync_db_async(get_data_dir())
    return {"ok": True, "updated_at": updated_at, "html": markdown.render_markdown(req.text)}
```

(`markdown` is already imported in `app.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_site_notes_routes.py -v`
Expected: PASS (the 2 new tests + all pre-existing notes-route tests — the invalid-id 400 and persistence tests are unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_notes_routes.py
git commit -m "feat(notes): save endpoint returns rendered markdown html"
```

---

## Task 2: View/edit toggle in the note editor + detail `note_html`

**Files:**
- Modify: `src/aishelf/site/app.py` (`video_detail`, `blog_detail`)
- Modify: `src/aishelf/site/templates/_note_editor.html`
- Modify: `src/aishelf/site/static/style.css`
- Test: `tests/unit/test_site_notes_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_site_notes_routes.py`:

```python
def test_detail_renders_note_as_markdown(client):
    client.post("/notes/youtube-aaa", json={"text": "**加粗笔记**"})
    r = client.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert "<strong>加粗笔记</strong>" in r.text   # rendered in the view block
    assert 'id="note-view"' in r.text
    assert 'id="note-edit-btn"' in r.text


def test_detail_without_note_shows_editor(client):
    r = client.get("/videos/youtube-aaa")            # no note saved yet
    assert r.status_code == 200
    assert 'id="note"' in r.text                     # textarea present
    assert 'id="note-view" class="note-view post-body" hidden' in r.text  # view hidden
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_site_notes_routes.py -k "as_markdown or shows_editor" -v`
Expected: FAIL (`id="note-view"`/`id="note-edit-btn"` not present — the template has no view block yet).

- [ ] **Step 3: Pass `note_html` from the detail routes**

In `src/aishelf/site/app.py`, replace `video_detail`'s body:

```python
@app.get("/videos/{item_id}", response_class=HTMLResponse)
def video_detail(request: Request, item_id: str):
    item = next((it for it in views.videos(_items()) if it.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404)
    note = _note_for(item)
    return templates.TemplateResponse(
        request,
        "video_detail.html",
        {"item": item, "section_url": "/videos", "note": note,
         "note_html": markdown.render_markdown(note)},
    )
```

And `blog_detail`'s return (keep the existing `body_html` computation above it):

```python
    note = _note_for(item)
    return templates.TemplateResponse(
        request,
        "blog_detail.html",
        {"item": item, "section_url": "/blogs", "note": note,
         "note_html": markdown.render_markdown(note), "body_html": body_html},
    )
```

- [ ] **Step 4: Rewrite the note partial**

Replace the entire contents of `src/aishelf/site/templates/_note_editor.html` with:

```html
<section class="notes">
  <div class="notes-head">
    <h2>我的笔记</h2>
    <button id="note-edit-btn" type="button" class="btn-link"{% if not note %} hidden{% endif %}>编辑</button>
  </div>
  <div id="note-view" class="note-view post-body"{% if not note %} hidden{% endif %}>{{ note_html | safe }}</div>
  <div id="note-edit"{% if note %} hidden{% endif %}>
    <textarea id="note" class="note-input" placeholder="写点笔记…（支持 Markdown）">{{ note }}</textarea>
    <div class="note-bar">
      <button id="note-save" type="button" class="btn">保存笔记</button>
      <span id="note-status" class="note-status"></span>
    </div>
  </div>
</section>
<script>
(function () {
  const view = document.getElementById("note-view");
  const edit = document.getElementById("note-edit");
  const editBtn = document.getElementById("note-edit-btn");
  const ta = document.getElementById("note");
  const saveBtn = document.getElementById("note-save");
  const status = document.getElementById("note-status");

  function showEdit() { view.hidden = true; editBtn.hidden = true; edit.hidden = false; ta.focus(); }
  function showView() { edit.hidden = true; view.hidden = false; editBtn.hidden = false; }

  editBtn.addEventListener("click", showEdit);

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    status.className = "note-status";
    status.textContent = "保存中…";
    try {
      const r = await fetch("/notes/{{ item.id }}", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: ta.value }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      status.textContent = "已保存 ✓";
      if (ta.value.trim()) { view.innerHTML = data.html; showView(); }
    } catch (e) {
      status.className = "note-status err";
      status.textContent = "保存失败：" + e;
    } finally {
      saveBtn.disabled = false;
    }
  });
})();
</script>
```

- [ ] **Step 5: Add styles**

Append to `src/aishelf/site/static/style.css`:

```css
.notes-head { display: flex; align-items: baseline; justify-content: space-between; }
.note-view { margin: 6px 0 4px; }
.note-view:empty { display: none; }
.btn-link { background: none; border: none; color: #0a84ff; cursor: pointer; font-size: 13px; padding: 0; }
.btn-link:hover { text-decoration: underline; }
```

- [ ] **Step 6: Run the notes tests + full suite**

Run: `pytest tests/unit/test_site_notes_routes.py -v` then `pytest -q`
Expected: PASS — the 2 new tests, the pre-existing notes tests (the textarea is still in the DOM, just inside the `hidden` edit block, so `id="note"` / prefilled-note assertions still hold), and the whole suite.

- [ ] **Step 7: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/_note_editor.html src/aishelf/site/static/style.css tests/unit/test_site_notes_routes.py
git commit -m "feat(notes): markdown view with 编辑 toggle on detail pages"
```

---

## Task 3: Documentation + full-suite verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

READ `CLAUDE.md` first. In the description of `notes.py` / the detail pages (the part that mentions per-item notes), add a terse note that detail-page notes now render Markdown with a view/edit toggle (rendered server-side via `markdown.render_markdown`), and that `POST /notes/{id}` returns the rendered `html`. Weave into the existing terse style; verify against `app.py` + `_note_editor.html` before committing.

- [ ] **Step 2: Run the full test suite**

Run: `pytest -q`
Expected: PASS (network tests skipped by default).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note markdown view + 编辑 toggle"
```

---

## Self-Review

- **Spec coverage:** save endpoint returns rendered `html` (Task 1) ✓; detail routes pass `note_html` (Task 2) ✓; `_note_editor.html` view/edit blocks with server-decided initial visibility (`{% if not note %}hidden`) + 「编辑」 toggle + save-swaps-view-via-innerHTML JS (Task 2) ✓; empty-note → editor shown, save-empty stays in editor (`{% if note %}` + `ta.value.trim()` guard) ✓; `.post-body` reuse + `.note-view`/`.btn-link` styles (Task 2) ✓; safety via server-sanitized `note_html`/`html` + `| safe`/`innerHTML` ✓; tests for save-html, empty-html, markdown-rendered-in-view, no-note-shows-editor ✓; docs (Task 3) ✓. Non-goals (no live preview, no new renderer/config, no history, no toolbar) — no task adds them.
- **Placeholder scan:** none — every code step has full code; every run step has command + expected outcome.
- **Type consistency:** save response keys `{ok, updated_at, html}` (Task 1) match the client reading `data.html` (Task 2); context keys `note` + `note_html` (Task 2 routes) match the template's `{{ note }}` / `{{ note_html | safe }}` and the `{% if note %}` guards; element ids `note-view`/`note-edit`/`note-edit-btn`/`note`/`note-save`/`note-status` consistent between template and JS and the test assertions. The Task-2 test string `'id="note-view" class="note-view post-body" hidden'` matches the exact attribute order written in the partial.

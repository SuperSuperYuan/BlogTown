# 笔记 Markdown 展示 + 重新编辑 (Note Markdown View) — Design

**Date:** 2026-06-17
**Status:** Approved, ready for implementation plan

## Problem

A per-item note on the detail page is currently an always-on `<textarea>` + 保存
button (`_note_editor.html`). Once written, the note is only ever shown as raw
text in the editing box — Markdown is never rendered. The user wants: **after a
note is written, show it as rendered Markdown; and allow re-editing.**

The project already has everything needed: `markdown.render_markdown(text)` (a
sanitized server-side Markdown→HTML renderer, used by self-authored blog bodies
and the 写博客 live-preview route), and the `.post-body` Markdown typography class.

## Goal

The note section becomes a **view ⇄ edit** toggle:
- A note with content shows **rendered Markdown** by default, with an 「编辑」 button.
- 「编辑」 switches to the textarea editor (prefilled with the raw note).
- 保存 persists the note and switches back to the rendered view **without a page
  reload** (the save response returns the freshly rendered HTML).
- An empty note shows the editor directly (start writing).

## Locked design decisions

- **Interaction:** view/edit toggle (not a live side-by-side preview).
- **Rendering:** server-side via the existing `markdown.render_markdown` (sanitized
  with nh3). No client-side Markdown library, no new renderer, no new config.
- **Styling:** the rendered note reuses the existing `.post-body` Markdown
  typography (consistent with self-authored blog bodies), scoped under `.notes`.
- **Persistence unchanged:** notes are still stored by `notes.py` as today; only
  the route's JSON response and the template change.

## Architecture

Two template blocks toggled by a few lines of vanilla JS; the server renders the
Markdown both on initial load (detail route) and on save (the note route returns
HTML). This mirrors the existing self-authored-blog rendering path
(`render_markdown` → `| safe`), so the trust/sanitization story is identical.

### 1. Detail routes — `src/aishelf/site/app.py`

`video_detail` and `blog_detail` already pass `note=_note_for(item)`. Add a
rendered-HTML field to each context:

```python
note = _note_for(item)
... {"item": item, "section_url": "/videos", "note": note,
     "note_html": markdown.render_markdown(note)}
```

(`markdown` is already imported. For `blog_detail`, add `note_html` alongside the
existing `note`/`body_html` keys.)

### 2. Note save route — `POST /notes/{item_id}` (`src/aishelf/site/app.py`)

Currently persists the note and returns the updated timestamp. Extend the response
to also include the rendered HTML so the client can swap the view in place:

```python
updated_at = notes.save_note(item_id, req.text)
...
return {"updated_at": updated_at, "html": markdown.render_markdown(req.text)}
```

The off-thread DB re-sync (so the note is searchable) is unchanged. The
invalid-id → 400 behavior is unchanged.

### 3. Note partial — `src/aishelf/site/templates/_note_editor.html`

Two blocks inside the existing `<section class="notes">`:

- **View** — `<div id="note-view" class="note-view post-body">{{ note_html | safe }}</div>`
  plus an 「编辑」 button (`#note-edit-btn`).
- **Edit** — the existing `<textarea id="note">{{ note }}</textarea>` + 保存
  (`#note-save`) + status (`#note-status`), wrapped in a container (`#note-edit`).

Initial visibility (server-decided, no flicker): when `note` is non-empty, render
View visible and Edit hidden; when empty, Edit visible and View hidden. Implement
with a Jinja conditional on `note` setting an inline `hidden` attribute / `style`
or a class on each block.

JS behavior:
- 「编辑」 → hide View, show Edit, focus the textarea.
- 保存 → `POST /notes/{id}` with `{text}` (as today). On success: read `html` from
  the response; if the saved text is non-empty, set `#note-view` innerHTML to
  `html`, show View, hide Edit; if empty, keep Edit shown. Status shows 已保存 ✓;
  on failure, the existing error handling stands.
- The injected `html` is server-sanitized (nh3), so `innerHTML` is safe — same
  path as the blog body.

### 4. Styles — `src/aishelf/site/static/style.css`

A small `.note-view` rule (spacing) — the heavy lifting is the reused `.post-body`
typography. Style/position the 「编辑」 button (reuse the existing `.btn`).

## Data flow

```
GET detail → _note_for(item) → markdown.render_markdown(note) → note_html
           → _note_editor.html: View (rendered) if note else Edit (textarea)
「编辑」 → show textarea (raw note)
保存 → POST /notes/{id} {text} → {updated_at, html}
     → client swaps #note-view innerHTML = html, back to View
```

## Error handling / edge cases

- Empty note on load → editor shown, no view.
- Saving an empty note → stay in editor (nothing to render).
- `render_markdown` never raises (falls back to escaped plain text), so a bad note
  can't crash the detail page or the save response.
- Invalid (non-path-safe) item id on save → 400 (unchanged).

## Testing

- **`POST /notes/{id}`**: response includes `html` that renders the saved Markdown
  (e.g. `**重点**` → contains `<strong>重点</strong>`); the note is still persisted
  (a subsequent load returns it) and `updated_at` is present; an empty `text`
  returns `html == ""`. Malformed id still → 400.
- **Detail route**: for an item with a Markdown note, the rendered page contains the
  note's rendered HTML (e.g. `<strong>` / `<em>` from the note text) inside the
  `note-view` block; for an item with no note, the editor textarea is shown and no
  `note-view` content is rendered.
- (`markdown.render_markdown` itself is already covered by existing tests.)

## Files

- Modify: `src/aishelf/site/app.py` (`video_detail`, `blog_detail`, `POST /notes/{item_id}`),
  `src/aishelf/site/templates/_note_editor.html`, `src/aishelf/site/static/style.css`.
- Tests: `tests/unit/test_site_notes_routes.py` (save returns html) and a detail-render
  assertion (existing `tests/unit/test_site_*` for detail, or add to the notes-routes test).

## Non-goals (YAGNI)

- No live side-by-side preview (that's the 写博客 page's model; notes use toggle).
- No new Markdown renderer, dependency, or config.
- No note history/versioning; no change to note storage (`notes.py`).
- No Markdown toolbar/buttons.

## Documentation touch-ups (on implementation)

- `CLAUDE.md`: note that detail-page notes now render Markdown (view/edit toggle)
  via `markdown.render_markdown`, and that `POST /notes/{id}` returns the rendered
  `html`.

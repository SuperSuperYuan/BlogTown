# Delete Items — Design Spec

**Date:** 2026-06-05
**Status:** Approved (pending spec review)

## Purpose

Let the user delete any collected video/blog from its detail page. Deleting an
item removes its content record and its note.

Depends on: `src/aishelf/site/` (display site), `src/aishelf/site/notes.py`,
`src/aishelf/contract/` (item ids), `src/aishelf/site/config.py`.

## Decisions (locked during brainstorming)

- **Delete scope:** remove the content record `data/{videos,blogs}/<id>.json`
  AND the note `data/notes/<id>.json` (clear everything about the item).
- **No re-collection blocklist** (v1): delete removes the current files; if
  Hermes later re-collects the same source, the item may reappear. Acceptable.
- **Control location:** a delete button on the detail page only (not list cards).
  After deletion, redirect back to the item's section list.

## Scope

In scope: an `items` module with id-safe deletion; a `POST /delete/{id}`
endpoint; a delete button (with confirm) on the video and blog detail pages;
refactor of the id validator shared with notes.

Out of scope (YAGNI): batch delete, trash/undo, list-card delete controls,
re-collection blocklist, auth.

## Architecture

```
Detail page (/videos/{id} or /blogs/{id})
   delete button → confirm() → POST /delete/{id}
        ▼
items.delete_item(id)  → safe_id(id); unlink data/videos|blogs/<id>.json + data/notes/<id>.json
        ▼  {ok: true}  (404 if nothing matched, 400 if id invalid)
Browser redirects to the section list (/videos or /blogs).
```

## Components / Files

- Create: `src/aishelf/site/items.py`
  - `safe_id(item_id) -> str` — the canonical content-id validator: rejects
    empty, `..`, `/`, `\`, and anything outside `^[A-Za-z0-9._-]+$`
    (`ValueError`). This is the existing notes validator, lifted here so notes
    and delete share one implementation.
  - `delete_item(item_id) -> bool` — calls `safe_id`; deletes
    `data/videos/<id>.json` and `data/blogs/<id>.json` if present, plus
    `data/notes/<id>.json` if present; returns `True` if a content record (video
    or blog) was removed, else `False`. Uses `missing_ok` unlink so a missing
    note is fine.
- Modify: `src/aishelf/site/notes.py` — replace the private `_safe_id` with
  `from aishelf.site.items import safe_id` and call `safe_id(...)`. (No behavior
  change; removes duplication. `items` does not import `notes`, so no cycle.)
- Modify: `src/aishelf/site/app.py` — add `POST /delete/{item_id}`:
  invalid id → 400; `delete_item` returns `False` → 404; success → `{"ok": true}`.
- Create: `src/aishelf/site/templates/_delete_button.html` — a danger-styled
  「删除」button + inline JS (confirm → POST `/delete/{{ item.id }}` → on ok,
  `window.location = section_url`). Included by both detail templates.
- Modify: `src/aishelf/site/templates/video_detail.html`, `blog_detail.html` —
  include `_delete_button.html` (both already receive `item` and `section_url`).
- Modify: `src/aishelf/site/static/style.css` — a `.btn-danger` style.

## API

`POST /delete/{item_id}` → JSON `{"ok": true}` on success.
- 400 if `item_id` fails `safe_id`.
- 404 if no video/blog record with that id exists.

## UI

On each detail page, below the note editor, a red「删除」button. Clicking it
shows `confirm("确定删除这条内容及其笔记？此操作不可恢复")`; on confirm it POSTs to
`/delete/{id}` and, on `{ok:true}`, navigates to `section_url` (`/videos` or
`/blogs`). On failure it shows an inline error message.

## Error Handling

- Invalid id (path traversal / bad charset) → `safe_id` raises → route returns 400.
- Unknown id (no matching record) → `delete_item` returns `False` → route 404.
- A missing note file during deletion is not an error (`unlink(missing_ok=True)`).

## Security

- `safe_id` is the single validation choke point; every unlinked path is built
  only from a validated id, so a crafted `/delete/...` cannot remove files
  outside `data/{videos,blogs,notes}/`.

## Testing

All tests run without network.

- **`items.py`:** `delete_item` removes the content record and the note and
  returns `True`; returns `False` for an unknown id (and deletes nothing);
  deletes a video that has no note (note `missing_ok`); `safe_id`/`delete_item`
  reject `..`, `/`, `\`, empty, out-of-charset (`ValueError`).
- **`notes.py` (regression):** existing notes tests still pass after the
  `safe_id` refactor (save/load round-trip, unsafe-id rejection).
- **Routes (`TestClient`, `AISHELF_DATA_DIR` = writable fixtures copy):**
  `POST /delete/{id}` removes `data/videos/<id>.json` (and note) and returns
  `{ok:true}`; a subsequent detail GET → 404; `POST /delete/<unknown>` → 404;
  `POST /delete/a..b` → 400; the detail page renders the delete button.

## Success Criteria

- On a video/blog detail page, the user can delete the item (after confirming);
  the record and its note are removed and the page redirects to the section.
- The item no longer appears in `/videos`/`/blogs` and its detail 404s.
- A path-traversal id is rejected (400); unknown id is 404.
- All unit and route tests (including the unchanged notes tests) pass.

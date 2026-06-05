# Notes — Design Spec

**Date:** 2026-06-05
**Status:** Approved (pending spec review)

## Purpose

Let the user write a personal note on each video/blog, viewable and editable on
the item's detail page. Notes are user-authored and mutable, distinct from the
Hermes-collected content records.

Depends on: `src/aishelf/site/` (display site) and `src/aishelf/contract/`
(item `id`s).

## Decisions (locked during brainstorming)

- **One editable note per item** (not multiple/timestamped). Open the detail
  page → see it → edit → save (overwrite).
- **Plain text** (multi-line, newlines preserved). No markdown rendering — zero
  XSS surface, zero dependencies.
- **Separate storage:** notes live in `data/notes/<id>.json`, keyed by the
  content item `id`, completely separate from the Hermes-owned content records.
  This is critical: Hermes idempotently overwrites `data/videos/<id>.json` on
  re-collection, so a note stored inside the record would be destroyed. Separate
  files mean notes survive re-collection.

## Scope

In scope: a notes storage module; a `POST /notes/{id}` save endpoint; a note
section (prefilled textarea + save button) on the video and blog detail pages;
id sanitization.

Out of scope (YAGNI): markdown rendering, multiple/timestamped notes per item,
a notes list/search page, note deletion UI (saving empty text clears it),
auth/multi-user.

## Architecture

```
Detail page GET (/videos/{id} or /blogs/{id})
   server-side: load content item + notes.load_note(id)  → prefill textarea
Browser edits note, clicks 保存
   POST /notes/{id}  { text }
        ▼
notes.save_note(id, text)  → atomic write data/notes/<id>.json {id, text, updated_at}
```

The display site gains its first **write** capability. All note I/O is isolated
in one module with id sanitization at the boundary.

## Components / Files

- `src/aishelf/site/notes.py`
  - `notes_dir() -> Path` — `get_data_dir() / "notes"`.
  - `_safe_id(item_id) -> str` — validates `item_id` matches `^[A-Za-z0-9._-]+$`
    and contains no path separators / `..`; raises `ValueError` otherwise.
    (Prevents path traversal, since `id` arrives from the URL.)
  - `load_note(item_id) -> str` — returns the saved note text, or `""` if none
    (or the file is missing/unreadable). Calls `_safe_id`.
  - `save_note(item_id, text) -> str` — atomic write of
    `{"id": item_id, "text": text, "updated_at": <iso>}` to
    `data/notes/<item_id>.json` (write `.tmp` then rename; create dir if needed);
    returns the `updated_at` stamp. Calls `_safe_id`. `updated_at` is produced by
    an injectable clock (default `datetime.now().isoformat(timespec="seconds")`)
    so tests are deterministic.
- `src/aishelf/site/app.py`
  - `POST /notes/{item_id}` — body `{"text": str}`; on invalid id → 400; saves
    via `notes.save_note`; returns JSON `{"ok": true, "updated_at": ...}`.
  - `video_detail` / `blog_detail` routes additionally pass `note=notes.load_note(item.id)`
    into their template context.
- `src/aishelf/site/templates/video_detail.html`, `blog_detail.html`
  - Include the shared note-editor partial (below), passing `item` and `note`.
- Create: `src/aishelf/site/templates/_note_editor.html` — the note section
  (textarea prefilled with `note`, a「保存笔记」button, a status span, and inline
  JS that posts to `/notes/{{ item.id }}`), included by both detail templates (DRY).

## Data Format

`data/notes/<id>.json`:

```json
{ "id": "youtube-EWvNQjAaOHw", "text": "我的笔记…", "updated_at": "2026-06-05T12:00:00" }
```

## UI

- On each detail page, below the existing content, a「我的笔记」section:
  a full-width `<textarea>` prefilled with the current note, a「保存笔记」button,
  and a status span ("保存中…" / "已保存 ✓" / "保存失败").
- Plain text only; rendered/edited via the textarea's value, so no HTML
  injection is possible.

## Error Handling

- Invalid/empty `item_id`, or one containing path separators or `..` → 400 (and
  `_safe_id` raises before any filesystem access).
- Empty `text` is allowed and clears the note (writes an empty-text record).
- A missing or unreadable note file → `load_note` returns `""` (detail page still
  renders).

## Security

- `_safe_id` is the single choke point: every path is built only from a
  validated id, so a crafted URL (`/notes/..%2f..%2fetc`) cannot escape
  `data/notes/`.

## Testing

All tests run without network.

- **`notes.py`:** `save_note` then `load_note` round-trips the text; `load_note`
  returns `""` for an unknown id; the file is written atomically with `id`/`text`/
  `updated_at`; `_safe_id` rejects ids with `/`, `..`, or other unsafe chars
  (`ValueError`); `save_note` with an injected clock yields a deterministic
  `updated_at`.
- **Routes (`TestClient`, `AISHELF_DATA_DIR` = tmp):** a detail page renders the
  textarea (and prefills an existing note saved beforehand); `POST /notes/{id}`
  with `{text}` returns 200 `{ok: true}` and writes `data/notes/<id>.json`; a
  follow-up detail GET shows the saved text; `POST /notes/<bad id>` → 400.

## Success Criteria

- On any video/blog detail page, the user can type a note, save it, reload the
  page, and see the note persisted.
- Notes live in `data/notes/` and are untouched by Hermes re-collection.
- A path-traversal id is rejected with 400; no file is written outside
  `data/notes/`.
- All unit and route tests pass.

# Atlas — Architecture Summary

**Status:** MVP complete (2026-06-05). 77 tests passing.

Atlas is a personal, local web app for collecting and browsing AI-domain content
(interview/technical-talk **videos** and **blog/document** articles) from across
the web, with personal **notes** on each item. Collection is delegated to an
external **Hermes** agent; Atlas owns the data contract, the browsing site, and
the editing actions.

> The Python package is `aishelf` (historical); the user-facing product name is
> **Atlas**.

---

## 1. The big picture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser                                                               │
│   /collect (Hermes chat) · /videos · /blogs · /<id> detail · /search   │
└───────────────┬─────────────────────────────────┬─────────────────────┘
                │ POST /collect/chat (SSE)         │ GET pages, POST /notes, POST /delete
                ▼                                  ▼
        ┌───────────────┐                  ┌──────────────────────────┐
        │  Hermes agent  │  writes JSON     │  Atlas site (FastAPI)     │
        │  (external,    │  records ───────▶│  reads + renders + edits  │
        │   OpenAI-compat)│                 └──────────────┬───────────┘
        └───────────────┘                                 │
                         ▲ system prompt with             │ load / validate
                         │ data path + JSON Schema         ▼
                         └───────────────  data/ (filesystem)  ◀──────────
                            videos/<id>.json  blogs/<id>.json  notes/<id>.json
```

The whole system is decoupled by **one data contract**: Hermes writes
contract-shaped JSON files into `data/`; the site reads them. Neither half knows
the other's internals — the site is built and tested entirely against fixtures,
with no dependency on Hermes.

---

## 2. Components

The package lives under `src/aishelf/` (src layout; `pytest.ini` sets
`pythonpath = src`).

### `aishelf.contract` — the data contract (the seam)

The authoritative definition of what a content record is. Shared by the
(future/external) writer and the reader.

| File | Responsibility |
|---|---|
| `models.py` | Pydantic v2 models: `ContentItem` base, `VideoItem`/`BlogItem` (discriminated on `type`), `parse_item`, `content_item_json_schema`. Unknown fields ignored. |
| `loader.py` | `load_items(data_dir)` — reads `videos/*.json` + `blogs/*.json`, validates each, **skips + logs** malformed files, returns typed items sorted by `published_at` desc. |
| `schema.py` | `write_schema()` — exports the JSON Schema to `docs/contract/content-item.schema.json` (the spec handed to Hermes). |

**Storage layout** (`data/`, gitignored):

```
data/
  videos/<id>.json     # one video record per file
  blogs/<id>.json      # one blog record per file
  notes/<id>.json      # one user note per item (separate from records)
  _failures/<id>.json  # (contract-defined) items a collector couldn't complete
```

- `id` = `<platform>-<native_id>` (e.g. `youtube-EWvNQjAaOHw`), or
  `blog-<sha1(url)[:12]>`; the filename stem equals the `id` field.
- **Atomic writes**: write `<id>.json.tmp`, then rename — readers never see a
  half-written file. Re-writing the same `id` is idempotent (overwrite).
- Records store **metadata + links only** (videos: thumbnail/embed/source;
  blogs: summary + source). No video files, no full article bodies.

### `aishelf.site` — the web app (FastAPI + Jinja2, server-rendered)

| File | Responsibility |
|---|---|
| `app.py` | All routes; thin layer over the modules below. |
| `config.py` | `get_data_dir()` ← `AISHELF_DATA_DIR` (default `data`). |
| `views.py` | Pure functions over `list[ContentItem]`: `videos`/`blogs` split, `search`, `by_keyword`, `by_author`/`author_key`, `paginate` (+ `Page`). No I/O — fully unit-tested. |
| `hermes.py` | Hermes connection (`HERMES_BASE_URL`/`_API_KEY`/`_MODEL`) + `stream_chat` — robust SSE: skips empty/`None` chunks, turns any error into an SSE error event (never breaks the stream). |
| `collect.py` | `build_collection_instructions(data_dir)` — the system prompt that tells Hermes the absolute data path, id/atomic-write rules, content rules, and embeds the JSON Schema. |
| `notes.py` | `load_note`/`save_note` — atomic, concurrency-safe (unique tempfile) per-item note I/O under `data/notes/`. |
| `items.py` | `safe_id` (the shared id validator — path-traversal safe) and `delete_item` (record + note). |
| `__main__.py` | `python -m aishelf.site` (uvicorn launcher; `AISHELF_SITE_HOST/PORT`). |
| `templates/` | Jinja2 (autoescaped): `base` + page templates + partials (`_video_card`, `_blog_row`, `_pager`, `_keywords`, `_note_editor`, `_delete_button`). |
| `static/style.css` | All styling (no build step). |

---

## 3. Routes

| Method & path | Purpose |
|---|---|
| `GET /` | Home: latest videos + blogs preview |
| `GET /videos`, `GET /blogs` | Section grids/lists; `?page=`, `?keyword=`, `?q=` |
| `GET /videos/{id}`, `GET /blogs/{id}` | Detail (embed/cover, summary, keywords, **note editor**, **delete button**) |
| `GET /authors/{key}` | An author's videos + blogs |
| `GET /search?q=` | Cross-modality search, grouped by type |
| `GET /collect` | **Hermes** chat page |
| `POST /collect/chat` | SSE proxy: prepends the collection instruction, streams Hermes |
| `POST /notes/{id}` | Save a note (`{text}`) → `{ok, updated_at}` |
| `POST /delete/{id}` | Delete record + note → `{ok}` (400 bad id, 404 unknown) |

---

## 4. Key flows

- **Collection:** user types a request in `/collect` → backend prepends the
  system instruction (abs `data/` path + JSON Schema) → streams to Hermes →
  **Hermes crawls and writes** `data/{videos,blogs}/<id>.json` itself → user
  refreshes `/videos`/`/blogs` to see new content.
- **Browse:** each request `load_items(data_dir)` (small corpus → always fresh,
  picks up new Hermes output with no restart) → `views` filter/search/paginate →
  Jinja render.
- **Note:** detail page prefills the saved note; saving POSTs to `/notes/{id}` →
  atomic write under `data/notes/`. Independent of the content record.
- **Delete:** confirm → `POST /delete/{id}` → `items.delete_item` unlinks the
  record (videos or blogs) + the note → redirect to the section.

---

## 5. Conventions & cross-cutting concerns

- **id safety:** `items.safe_id` is the single validation choke point (charset
  `[A-Za-z0-9._-]`, rejects `..`/`/`/`\`); every filesystem path is built only
  from a validated id. Reused by `notes` and `delete`.
- **Atomic writes** everywhere user/agent data is persisted (`.tmp` + rename;
  notes use a unique tempfile for concurrency safety).
- **Resilient reads:** a single malformed record/note is skipped + logged, never
  crashes a page.
- **XSS:** templates autoescape; scraped URLs pass a `safe_url` filter
  (http/https only) before landing in `href`/`src`.
- **Tech stack:** Python 3.11+, FastAPI, Jinja2, uvicorn, pydantic v2, `openai`
  SDK (Hermes is OpenAI-compatible). Deps in `pyproject.toml`.

### Running

```bash
pip install -e ".[dev]"
python -m aishelf.site        # Atlas site, default :8001 (AISHELF_DATA_DIR=data)
pytest                        # 77 tests; network tests deselected by default
```

Hermes must be running (default `http://127.0.0.1:8642/v1`) for `/collect` to
work; everything else works against whatever is already in `data/`.

### Testing

TDD throughout; **Hermes/network is always mocked** (live calls only under the
`network` marker). Pure logic (`views`, `models`, `loader`, `items`, `notes`,
`collect`) is unit-tested; routes via FastAPI `TestClient` against fixture data
dirs. Fixtures live in `tests/fixtures/contract/`.

---

## 6. Scope & known caveats

**Out of scope (deliberate, YAGNI):** auth/multi-user; markdown rendering in
notes; multiple notes per item; batch delete / trash / undo; a re-collection
blocklist; backend re-validation of files Hermes writes; live push to the
browser (the user refreshes).

**Caveats:**
- **Re-collection resurrection:** deleting an item only removes the current
  files; if Hermes later re-collects the same source, it can reappear (no
  blocklist).
- **Local single-user:** note history persistence is per-browser (localStorage
  for the chat); the dev Hermes API key has a committed default in `hermes.py`
  for local convenience — move it to env-only if it's ever a real credential.
- **Historical:** the M1 spec/plan (`docs/.../2026-05-28-m1-scraper*`) and the
  Hermes-WebUI spec/plan (`docs/.../2026-06-02-hermes-webui*`) predate the
  current architecture and are kept only as design history.

---

## 7. Design history

Each piece has its own spec → plan in `docs/superpowers/`:

| Sub-project | Spec / plan date |
|---|---|
| Content data contract | 2026-06-03 |
| Display site | 2026-06-03 |
| Collect page (Hermes chat) | 2026-06-04 |
| Notes | 2026-06-05 |
| Delete items | 2026-06-05 |
| (superseded) Hermes WebUI, M1 scraper | 2026-06-02, 2026-05-28 |

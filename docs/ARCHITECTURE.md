# Atlas — Architecture Summary

**Status:** MVP + collection access control + scheduling + derived SQLite
search DB + ask-your-library RAG chat + hybrid FTS5/semantic retrieval +
knowledge graph (2026-06-15). 264 tests passing.

Atlas is a personal, local web app for collecting and browsing AI-domain content
(interview/technical-talk **videos** and **blog/document** articles) from across
the web, with personal **notes** on each item. Collection is delegated to an
external **Hermes** agent; Atlas owns the data contract, the browsing site, and
the editing actions. Collection can be triggered interactively (the Hermes chat)
or on a **daily schedule**, and is gated by a **passcode allowlist**. A derived
**SQLite + FTS5** index gives CJK-aware full-text search over the contract files
(a rebuildable view; files stay the source of truth).

> The Python package is `aishelf` (historical); the user-facing product name is
> **Atlas**.

---

## 1. The big picture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Browser                                                                   │
│   /collect (Hermes chat) · /videos · /blogs · /<id> detail · /search       │
└───────────────┬─────────────────────────────────┬─────────────────────────┘
                │ POST /collect/chat (SSE)         │ GET pages, GET /api/search,
                ▼                                  ▼  POST /notes, POST /delete
        ┌───────────────┐                  ┌──────────────────────────┐
        │  Hermes agent  │  writes JSON     │  Atlas site (FastAPI)     │
        │  (external,    │  records ───────▶│  reads + renders + edits  │
        │   OpenAI-compat)│                 └──────┬───────────────┬────┘
        └───────────────┘             load/validate│               │ FTS5 query
                         ▲ system prompt with       ▼               ▼
                         │ data path + JSON Schema  data/ ──sync──▶ atlas.db
                         └─────────────  videos/  blogs/  notes/   (derived DB)
```

The whole system is decoupled by **one data contract**: Hermes writes
contract-shaped JSON files into `data/`; the site reads them. Neither half knows
the other's internals — the site is built and tested entirely against fixtures,
with no dependency on Hermes. `atlas.db` is a **derived view** synced from the
files (rebuildable any time); the files remain the source of truth.

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
| `app.py` | All routes + the scheduler lifespan; thin layer over the modules below. `_require_collect_token` is the shared passcode gate for collection + schedule mutations. |
| `config.py` | `get_data_dir()` ← `AISHELF_DATA_DIR` (default `data`). |
| `views.py` | Pure functions over `list[ContentItem]`: `videos`/`blogs` split, `search`, `by_keyword`, `by_author`/`author_key`, `paginate` (+ `Page`). No I/O — fully unit-tested. |
| `hermes.py` | Hermes connection (`HERMES_BASE_URL`/`_API_KEY`/`_MODEL`) + `stream_chat` — robust SSE: skips empty/`None` chunks, turns any error into an SSE error event (never breaks the stream). API key is env-only (no committed default). |
| `collect.py` | `build_collection_instructions(data_dir)` — the system prompt that tells Hermes the absolute data path, id/atomic-write rules, content rules, and embeds the JSON Schema. `run_once(prompt)` — a non-streaming collection call used by the scheduler. |
| `ask.py` | RAG core for `/ask` (pure): `retrieve` — hybrid vector cosine + FTS5 when `ATLAS_EMBED_*` is configured (vector recall unioned with bigram-floored FTS5 safety net, cosine-reranked above a similarity floor), pure FTS5 fallback otherwise; `build_messages` (grounded system prompt: numbered sources, `[n]` citations, no-source guard), `source_refs`, `latest_user_question`. Also `nav_types`/`nav_candidates`/`nav_refs` (content jump-cards on explicit open/view intent) and `is_low_confidence` (empty retrieval → collect guide; `retrieve` already owns the relevance gate, so the guide fires exactly when retrieval returned nothing). |
| `llm.py` | Chat-model connection for answering (`ATLAS_CHAT_*`, defaulting to Hermes) + robust `stream_completion` (reuses `hermes.sse`). |
| _(package root)_ `embed.py` | OpenAI-compatible embedding client (`ATLAS_EMBED_*`): `is_configured`, `model_name`, `embed_texts`, `embed_query`. **No default** (the chat/Hermes provider does not serve embeddings); unset ⇒ every call returns `None`, silently disabling semantic retrieval. All errors are swallowed to `None` so reads never crash. |
| `allowlist.py` | Collect passcode gate: `load_tokens`/`is_allowed` over `config/collect_allowlist.txt` (one token per line, `#` comments). Read per request; **fail-closed** (missing/empty ⇒ nobody). |
| `schedules.py` | `Schedule` model + `load_schedules`/`save_schedules` (atomic YAML at `config/schedules.yaml`) + `due_schedules(schedules, state, now)` — the pure "what should run now" function. |
| `schedule_state.py` | `load_state`/`save_state` — atomic per-schedule last-run dates at `data/schedule_state.json` (so missed runs catch up across restarts). |
| `scheduler.py` | `run_due_now()` (run due schedules, record success, log+retry failures) + a daemon thread loop started from the lifespan when `AISHELF_SCHEDULER_ENABLED` is set. |
| `notes.py` | `load_note`/`save_note` — atomic, concurrency-safe (unique tempfile) per-item note I/O under `data/notes/`. |
| `items.py` | `safe_id` (the shared id validator — path-traversal safe) and `delete_item` (record + note). |
| `__main__.py` | `python -m aishelf.site` (uvicorn launcher; `AISHELF_SITE_HOST/PORT`; sets `AISHELF_SCHEDULER_ENABLED=1` by default). |
| `templates/` | Jinja2 (autoescaped): `base` + page templates + partials (`_video_card`, `_blog_row`, `_pager`, `_keywords`, `_note_editor`, `_delete_button`). |
| `static/style.css` | All styling (no build step). |

### `aishelf.db` — the derived search index

A SQLite mirror of the contract files plus a CJK-aware FTS5 index. It is a
**derived view**: files are the source of truth, the DB is rebuildable at any
time (`python -m aishelf.db sync [--rebuild]`). There is **no** startup or
periodic sync — it is synced explicitly after each collection (scheduled runs,
and off-thread after manual chat collection) and once at deploy to backfill.

| File | Responsibility |
|---|---|
| `config.py` | `default_db_path(data_dir)` ← `AISHELF_DB_PATH` (default `<data_dir>/atlas.db`). |
| `schema.py` | `connect`/`init_db` — the `items` table + external-content FTS5 `items_fts` (bigram-tokenized title/summary/keywords/author/**note**) + `edges` table (`src TEXT, dst TEXT, weight REAL, PRIMARY KEY(src,dst)` — undirected, stored canonically with `src < dst`). The `note` column lets `/ask` and `/api/search` reach into your own annotations. Three nullable columns added for semantic retrieval: `embedding BLOB`, `embedding_model TEXT`, `embedding_dim INTEGER`. Existing deployments must run `python -m aishelf.db sync --rebuild` once to populate all new columns and backfill `edges`. |
| `tokenize.py` | `bigrams`/`to_match_query` (AND) + `to_match_query_or` (OR) — CJK bigram tokenization so Chinese text is searchable without word segmentation. |
| `sync.py` | `sync(data_dir, db_path)` — idempotent: upsert every contract file (incl. its note text), prune rows whose file is gone. When `ATLAS_EMBED_*` is configured, also computes and stores embeddings incrementally (re-embeds new/changed items and any whose stored model name differs from the current one), then updates `edges` incrementally — `recompute_edges_for` on the (re)embedded ids and `delete_edges_for` on pruned items, all in the same transaction. Embedded text is `title + summary + keywords + note` — author is deliberately excluded. Embedding failure leaves rows intact without crashing; unconfigured ⇒ no embeddings, no edges (empty graph). |
| `vector.py` | Float32 BLOB `pack`/`unpack`, `load_embeddings(db_path, dim)` (returns ids + an (N, dim) numpy matrix, filtered to rows whose stored dim matches the query dim), and brute-force `cosine_search`. No vector index — exhaustive cosine is sub-100 ms at personal-library scale. |
| `search.py` | `search(db_path, q, *, type=None, limit, offset, mode="and")` — FTS5 query → structured hits, paginated; `mode="or"` is the lenient retrieval path used by `/ask`. `get_by_ids(db_path, ids)` hydrates a list of ids into a `{id: SearchHit}` map (used by the hybrid retrieval path). |
| `graph.py` | Semantic knowledge graph over the embedded corpus. `neighbors(vec, ids, matrix, *, floor=GRAPH_SIM_FLOOR, exclude=None)` — cosine similarity pairs above `GRAPH_SIM_FLOOR` (0.5). `recompute_edges_for(con, ids)` / `delete_edges_for(con, ids)` — incremental edge maintenance (called from `sync`). `load_graph(db_path, *, cap_k)` — read side: all nodes + edges, each node's neighbour list capped to top-K=`GRAPH_TOP_K` (8) strongest edges by union over endpoints, with degree. |
| `__main__.py` | `python -m aishelf.db sync [--rebuild]` (backfill / drop+recreate; `--rebuild` also drops `edges`). |

---

## 3. Routes

| Method & path | Purpose |
|---|---|
| `GET /` | Home: latest videos + blogs preview |
| `GET /videos`, `GET /blogs` | Section grids/lists; `?page=`, `?keyword=`, `?q=` |
| `GET /videos/{id}`, `GET /blogs/{id}` | Detail (embed/cover, summary, keywords, **note editor**, **delete button**) |
| `GET /authors/{key}` | An author's videos + blogs |
| `GET /search?q=` | Cross-modality search page, grouped by type (reads files) |
| `GET /api/search?q=&type=&page=` | Read-only JSON search over the derived DB (FTS5) — `{q, type, page, results}` |
| `GET /ask` | Ask-your-library chat page (ungated; per-browser history). |
| `POST /ask/chat` | SSE: `{sources}`, then optionally `{jump}` (open-intent jump-cards) or `{collect}` (empty→collect guide; takes precedence), then the streamed answer. **Ungated.** |
| `GET /collect` | **Hermes** chat page + the 「定时采集」schedule section; `?q=` pre-fills the collection composer. |
| `POST /collect/chat` | SSE proxy: prepends the collection instruction, streams Hermes. **Gated** by the collect passcode (`X-Collect-Token`) |
| `POST /schedules` | Create/edit (upsert by name) a schedule. **Gated** (400 bad name/time/empty prompt) |
| `POST /schedules/{name}/toggle` | Enable/disable a schedule. **Gated** (404 unknown) |
| `POST /schedules/{name}/delete` | Remove a schedule. **Gated** (404 unknown) |
| `GET /graph` | Semantic knowledge-graph page (Cytoscape.js, fcose layout): nodes colored by type, sized by degree; click → detail page; type filter + search highlight; empty state when no embeddings. |
| `GET /api/graph` | Read-only JSON `{nodes:[{id,type,title,author,degree}], edges:[{source,target,weight}]}` from `atlas.db`. |
| `POST /notes/{id}` | Save a note (`{text}`) → `{ok, updated_at}` |
| `POST /delete/{id}` | Delete record + note → `{ok}` (400 bad id, 404 unknown) |

"Gated" = requires a passcode in the allowlist via the `X-Collect-Token` header;
otherwise `403`. Browsing, notes, and delete are not gated.

---

## 4. Key flows

- **Collection:** user types a request in `/collect` (with a valid passcode) →
  backend gate checks the allowlist → prepends the system instruction (abs
  `data/` path + JSON Schema) → streams to Hermes → **Hermes crawls and writes**
  `data/{videos,blogs}/<id>.json` itself → user refreshes `/videos`/`/blogs`.
- **Scheduled collection:** while the site runs, a daemon thread wakes every 60s
  and runs `due_schedules` (enabled, past today's `HH:MM`, not yet run today per
  `schedule_state.json`); each due schedule re-runs its saved prompt via
  `collect.run_once`. Because Hermes writes idempotently by id, re-running a
  prompt just adds anything new — "collect if updated" needs no diffing. Missed
  runs (machine asleep) catch up on the next tick/startup; a failed run is
  logged and retried. Schedules are managed in the 「定时采集」section of
  `/collect`; the *runs* bypass the passcode (no human present) — the config
  file (writable only with the passcode or filesystem access) is the authorization.
- **Browse:** each request `load_items(data_dir)` (small corpus → always fresh,
  picks up new Hermes output with no restart) → `views` filter/search/paginate →
  Jinja render.
- **DB search:** `GET /api/search` queries `atlas.db` via FTS5 (bigram match) —
  no file scan. The DB is kept current by syncing after collection: scheduled
  runs sync inline, manual chat collection syncs off-thread once the stream ends.
  The page-rendered `/search` still reads files; `/api/search` is the DB path.
- **Ask:** `POST /ask/chat` retrieves the top-K items for the latest question,
  builds a grounded prompt (numbered sources, citation + no-hallucination rules),
  streams the answer from the `ATLAS_CHAT_*` model, and emits a `{sources}` event
  the page renders as links. Saving a note re-syncs the index so notes are
  searchable. **Retrieval is hybrid when `ATLAS_EMBED_*` is configured**: the
  question is embedded once; vector cosine recall over the whole corpus
  (semantic, cross-lingual) is unioned with bigram-floored FTS5 OR-mode hits as
  an exact-term safety net; vector hits are kept above a cosine similarity floor
  (0.30), FTS safety-net hits pass the same bigram-overlap floor as the FTS-only
  path; the union is capped at k. When embeddings are unavailable (unconfigured,
  service down, or corpus not yet embedded), retrieval falls back to the prior
  pure FTS5 + bigram-overlap floor path — behavior identical to before. When the
  turn reads as an explicit open/view request the answer also carries `{jump}`
  cards to detail pages; when retrieval returns nothing (the relevance gate is
  inside `retrieve()`) it carries a `{collect}` guide to `/collect?q=<question>`
  (low-confidence check precedes jump-cards and suppresses them).
- **Knowledge graph:** `GET /graph` calls `load_graph(db_path)` which reads all
  nodes and edges from `atlas.db`. Edges are cosine similarity pairs with weight
  ≥ `GRAPH_SIM_FLOOR` (0.5), stored canonically (`src < dst`) in the `edges`
  table. The read side caps each node to its top-K=`GRAPH_TOP_K` (8) strongest
  edges (union across both endpoints) and attaches degree, avoiding a hairball on
  dense corpora. Cytoscape.js renders the graph client-side (fcose layout); nodes
  are colored by type and sized by degree; clicking a node navigates to its detail
  page; the type filter and search highlight are client-side. The graph is empty
  (shows an empty-state message) when `ATLAS_EMBED_*` is unconfigured or the
  corpus has not been embedded yet. A one-time `python -m aishelf.db sync
  --rebuild` is required to backfill `edges` on an existing DB after upgrading.
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
- **Access control:** collection is costly, so the paths that spend the Hermes
  budget — `POST /collect/chat` and the schedule mutations — share one gate
  (`_require_collect_token` → `allowlist`). The passcode allowlist is read per
  request and **fail-closed**. The passcode travels in the `X-Collect-Token`
  header (plaintext — guards against accidental LAN triggering, not real attackers).
- **Config files** (`config/`): committed `*.example` templates, gitignored live
  files — `collect_allowlist.txt` (passcodes), `schedules.yaml` (timers),
  `authors.yaml` (legacy). The `*.example` variants are the documentation.
- **Tech stack:** Python 3.11+, FastAPI, Jinja2, uvicorn, pydantic v2, PyYAML,
  `openai` SDK (Hermes + embedding service are OpenAI-compatible), SQLite + FTS5
  (stdlib `sqlite3`, no extra dep), `numpy` (brute-force cosine for hybrid
  retrieval). Deps in `pyproject.toml`.

### Running

```bash
pip install -e ".[dev]"
python -m aishelf.site        # Atlas site + scheduler, default :8001 (AISHELF_DATA_DIR=data)
python -m aishelf.db sync     # backfill/refresh the derived DB (--rebuild to recreate)
pytest                        # 264 tests; network tests deselected by default
```

Hermes must be running (default `http://127.0.0.1:8642/v1`) for collection to
work; everything else works against whatever is already in `data/`. To collect,
add a passcode to `config/collect_allowlist.txt` and enter it on the page. On a
fresh deploy, run `python -m aishelf.db sync` once to backfill `/api/search`.
Extra env: `AISHELF_COLLECT_ALLOWLIST`, `AISHELF_SCHEDULES`,
`AISHELF_SCHEDULER_ENABLED` (launcher sets it; empty to disable), `AISHELF_DB_PATH`,
`ATLAS_EMBED_BASE_URL`/`_API_KEY`/`_MODEL` (optional; enables hybrid `/ask` retrieval
and the `/graph` knowledge graph — run `python -m aishelf.db sync --rebuild` once
after setting to backfill embeddings and `edges`).

### Testing

TDD throughout; **Hermes/network is always mocked** (live calls only under the
`network` marker). Pure logic (`views`, `models`, `loader`, `items`, `notes`,
`collect`) is unit-tested; routes via FastAPI `TestClient` against fixture data
dirs. Fixtures live in `tests/fixtures/contract/`.

---

## 6. Scope & known caveats

**Out of scope (deliberate, YAGNI):** full multi-user auth (only a shared
passcode gates collection); markdown rendering in notes; multiple notes per
item; batch delete / trash / undo; a re-collection blocklist; backend
re-validation of files Hermes writes; live push to the browser (the user
refreshes); cron-style schedules beyond daily `HH:MM`; per-run schedule limits.

**Caveats:**
- **Re-collection resurrection:** deleting an item only removes the current
  files; if Hermes later re-collects the same source, it can reappear (no
  blocklist).
- **Passcode is plaintext over the LAN:** the `X-Collect-Token` gate stops
  accidental/unauthorized collection by LAN visitors, but isn't real auth — keep
  Atlas on a trusted LAN, not the public internet.
- **Scheduling is in-process:** a schedule only fires while the site is running;
  if the machine is asleep / the site is down at the scheduled time, the run
  happens the next time the site is up that day (catch-up), not exactly on time.
- **Local single-user:** chat history persistence is per-browser (localStorage),
  which also holds the collect passcode.
- **DB sync is explicit, not automatic:** `atlas.db` is synced only after a
  collection (and at deploy via `python -m aishelf.db sync`). Editing files
  on disk by hand, or a first run before backfill, leaves `/api/search` stale
  until the next sync — by design (no startup/periodic sync). Rebuild any time.
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
| Collect allowlist (passcode gate) | 2026-06-05 |
| Scheduled collection | 2026-06-05 |
| Schedules UI (in `/collect`) | 2026-06-05 |
| Derived SQLite DB + FTS5 search | 2026-06-08 |
| Hybrid retrieval (FTS5 + embeddings) | 2026-06-10 |
| Knowledge graph | 2026-06-15 |
| (superseded) Hermes WebUI, M1 scraper | 2026-06-02, 2026-05-28 |

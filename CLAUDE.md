# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Atlas** (Python package `aishelf`) is a personal, local web app for collecting
and browsing AI-domain content — interview/technical-talk **videos** and
**blog/document** articles — with personal **notes** on each item.

Collection is delegated to an external **Hermes** agent (an OpenAI-compatible
API). The two halves are decoupled by a **data contract**: Hermes writes
contract-shaped JSON records into `data/`; the Atlas site reads and renders them.

The MVP is complete. Three logical pieces, each with a spec → plan in
`docs/superpowers/`:

| Piece | Role |
|---|---|
| **Contract** (`aishelf.contract`) | Pydantic models + loader + JSON Schema for the two content modalities; the seam between collection and display. |
| **Site** (`aishelf.site`) | FastAPI + Jinja2 server-rendered app: browse (videos/blogs/search/author), the Hermes collection chat, per-item notes, and delete. |
| **Hermes** (external) | Crawls sources and writes `data/{videos,blogs}/<id>.json` directly, instructed via a system prompt that embeds the JSON Schema. |

See **`docs/ARCHITECTURE.md`** for the full architecture.

## Commands

- Install with dev deps: `pip install -e ".[dev]"`
- Run the site: `python -m aishelf.site` (default `:8001`; `AISHELF_DATA_DIR` defaults to `data`)
- Export the contract JSON Schema: `python -m aishelf.contract.schema`
- Backfill/rebuild the derived DB: `python -m aishelf.db sync` (`--rebuild` to drop+recreate)
- Run tests (network skipped by default): `pytest`
- Run including network smoke tests: `pytest -m ""`
- Run a single test: `pytest tests/unit/test_site_views.py::test_name -v`

## Architecture

Source layout uses a `src/` directory; package is `aishelf`.

- `aishelf/contract/` — `models.py` (`VideoItem`/`BlogItem` discriminated on
  `type`, `parse_item`), `loader.py` (`load_items` — validate + skip-bad + sort),
  `schema.py` (export to `docs/contract/content-item.schema.json`).
- `aishelf/embed.py` (package root) — OpenAI-compatible embedding client
  (`ATLAS_EMBED_*`): `is_configured`, `model_name`, `embed_texts`, `embed_query`.
  No default; unset ⇒ every call returns `None` (silently disables semantic
  retrieval). All errors are swallowed to `None` so reads never crash.
- `aishelf/alias.py` (package root) — LLM short-alias client reading
  `ATLAS_CHAT_*` (same model as `/ask`): `is_configured`, `generate_aliases(pairs)`
  — batched, returns `None` when unconfigured, empty, error, or parse-mismatch
  (caller falls back to truncated title); also `generate_hooks(pairs)` — same
  batched LLM core, same `ATLAS_CHAT_*` gate, same None-on-failure degradation —
  returns a one-sentence ≤30-char Chinese "为什么值得看" hook per item for browse
  lists; also `generate_cluster_names(clusters)` — same batched core / same
  `ATLAS_CHAT_*` gate / same None-on-failure degradation — takes each theme
  cluster's representative titles and returns a ≤6-char Chinese galaxy name for
  `/graph`. Lives at package root so `db` can use it without importing `site`
  (same pattern as `embed.py`).
- `aishelf/site/` — `app.py` (routes + scheduler lifespan; browse/home/author
  routes surface per-item hooks via a `_hooks_for` helper that bridges
  `db_search.hooks_for` into the file-rendered lists), `views.py` (pure
  filter/search/paginate), `hermes.py` (Hermes connection + robust SSE
  `stream_chat`), `collect.py` (system-prompt builder + non-streaming
  `run_once`), `ask.py` (RAG core for `/ask`: `retrieve` — hybrid vector + FTS5
  when `ATLAS_EMBED_*` is configured, pure FTS5 fallback otherwise; `build_messages`,
  `source_refs`, plus `nav_types`/`nav_candidates`/`nav_refs` for jump-cards and
  `is_low_confidence` for the empty→collect guide — fires when `retrieve` returns
  nothing, since `retrieve` already owns the relevance gate), `llm.py` (chat-model
  client, `ATLAS_CHAT_*`, `stream_completion`), `notes.py` (per-item notes;
  detail routes pass `note_html` pre-rendered via `markdown.render_markdown`;
  the template `_note_editor.html` shows the rendered view by default with an 「编辑」
  button to switch to the textarea, and shows the textarea directly when there is no
  note yet; `POST /notes/{id}` saves the text and returns `{"html": …}` so the
  client swaps the view in place without a reload), `items.py` (`safe_id` +
  `delete_item`), `markdown.py` (render user markdown →
  sanitized HTML via markdown-it-py + nh3; never raises), `posts.py`
  (`create_post`/`read_post`/`update_post` for self-authored blogs; atomic writes
  like `notes.py`; pure persistence — route triggers the DB re-sync),
  `allowlist.py` (collect passcode gate),
  `schedules.py` (config load + pure `due_schedules`), `schedule_state.py`
  (last-run dates), `scheduler.py` (background `run_due_now` loop),
  `collide.py` (idea-collision: pure `pick_pair`/`random_pair` — a surprising
  pair with embedding cosine in a mid band [0.30, 0.50) below the graph edge
  floor, preferring cross-type/author — plus `load_pair_space` loader and
  `build_messages`; surfaced by `GET /collide` + `POST /collide/chat`, which
  emits the chosen pair then streams a three-part 中文 synthesis via
  `llm.stream_completion`; on-demand, no persistence, reuses `ATLAS_CHAT_*`/`ATLAS_EMBED_*`),
  `path.py` (语义路径: pure `build_messages` — given the ordered items on a graph
  path, phrases a 中文 explanation of the conceptual bridge; mirrors collide.py's
  pure half; streamed by `POST /graph/path` via `llm.stream_completion`),
  `digest.py` (今日速读: pure `build_digest` — recent items sorted by `collected_at` + one
  date-seeded older "gem" via `random.Random(today)`, each carrying its A-hook; no LLM/cache;
  rendered as a 今日速读 card at the top of `GET /`),
  `templates/`, `static/`, `__main__.py`.
- `aishelf/db/` — derived SQLite index of the contract files: `config.py`
  (`default_db_path`), `schema.py` (`items` table + FTS5 `items_fts`, plus
  `connect`/`init_db`; the `items` table now includes `embedding BLOB`,
  `embedding_model TEXT`, `embedding_dim INTEGER`, `alias TEXT`, `hook TEXT`, and
  `cluster INTEGER` (theme-galaxy id) — all
  nullable, backfilled by `sync --rebuild`), `tokenize.py` (CJK bigram
  `bigrams`/`to_match_query`),
  `sync.py` (idempotent `sync` — upsert + prune; when `ATLAS_EMBED_*` is
  configured, also computes and stores embeddings incrementally, re-embedding
  new/changed items and any whose stored model differs from the current one,
  then updates `edges` incrementally — recomputing edges for the (re)embedded
  ids and deleting edges of pruned items, all in the same transaction; when
  `alias.is_configured()`, also generates and stores a short Chinese node alias
  for new items and items whose title changed (and backfills any missing alias);
  note edits do NOT regenerate aliases; on the same title-keyed policy also
  generates and stores a per-item `hook` (new item / title change / missing;
  note edits do NOT regenerate it); then, on the same `embedded_ids or stale`
  condition as edges, recomputes theme clusters via `cluster.recompute_clusters`
  and (LLM-)names only clusters whose member signature is new (so note edits,
  which re-embed but don't move cluster boundaries, cost no naming call); all in
  the same transaction; empty
  graph/clusters when embeddings are unconfigured; embedding/alias/hook/cluster
  failure leaves rows intact without crashing), `vector.py`
  (float32 BLOB `pack`/`unpack`, `load_embeddings`, and brute-force numpy
  `cosine_search` — no vector index, exhaustive cosine over the corpus),
  `search.py` (`search` over FTS5; `get_by_ids` hydrates items by id into a
  `{id: SearchHit}` map; `hooks_for(db_path, ids)` → `{id: hook}` map — omits
  empty/missing entries; tolerant of a missing/old DB, returning `{}`), `graph.py` (semantic knowledge graph: `neighbors`
  cosine ≥ `GRAPH_SIM_FLOOR`; `recompute_edges_for`/`delete_edges_for` for
  incremental edge maintenance; `load_graph` reads nodes + edges with per-node
  top-K=`GRAPH_TOP_K` cap and returns each node with `alias` (or `""` → frontend
  truncates title) and a unit-sphere position `(x, y, z)` computed at read time
  by PCA of the embeddings — nodes without embeddings (or fewer than 3 embedded,
  or degenerate embeddings) get a deterministic `_hash_point` unit-sphere
  placement; each node also carries `cluster`/`collected_at`/`hook`, and the
  payload gains a top-level `clusters` list (`{id, name, color, size}`) for the
  主题星系 frontend; `author` is not included in node output; constants
  `GRAPH_SIM_FLOOR=0.5`, `GRAPH_TOP_K=8`),
  `cluster.py` (主题星系: pure `choose_k`/`kmeans` (deterministic numpy k-means on
  L2-normalized vectors, no sklearn)/`representatives`/`color_for`/`PALETTE`, plus
  the thin `recompute_clusters` that rewrites `items.cluster` + the `clusters`
  table and carries a cluster's name forward when its member signature is
  unchanged; lives in `db` so `sync` can use it without importing `site`, same as
  `graph.py`),
  `__main__.py` (CLI). `schema.py` also creates the `edges` table (`src TEXT,
  dst TEXT, weight REAL, PRIMARY KEY(src,dst)` — undirected, stored canonically
  with `src < dst`) and the `clusters` table (`id INTEGER PRIMARY KEY, name TEXT,
  color TEXT, signature TEXT`). The DB is a rebuildable view; files stay the
  source of truth.

**Data & storage** (`data/`, gitignored):

- `data/videos/<id>.json`, `data/blogs/<id>.json` — content records (metadata +
  links only). `data/notes/<id>.json` — user notes (kept separate from records).
  A blog record may be self-authored (`origin="self"`, markdown `body` field,
  written by `posts.py`, rendered inline on the detail page); collected blogs
  (`origin="collected"`, the default) are unchanged.
- `id` = `<platform>-<native_id>` (or `blog-<sha1(url)[:12]>`); filename stem
  equals the `id` field.
- **Atomic writes** (`.tmp` + rename) and **id sanitization** (`items.safe_id`,
  the single path-safety choke point) everywhere data is persisted.
- The loader/site **skip and log** a malformed record rather than crashing.

**Derived DB** (`aishelf.db`): a SQLite file (`<data_dir>/atlas.db`, gitignored)
holding a structured mirror of the contract records plus a bigram FTS5 index for
CJK full-text search. The `items_fts` table also indexes per-item note text (the
`note` column), so notes are searchable via `/api/search` and `/ask`. It is a
**derived view** — files remain the source of truth and the DB is rebuildable at
any time (`python -m aishelf.db sync`). It is synced after each collection
(scheduled runs, and off-thread after manual chat collection); saving a note also
triggers an off-thread re-sync so the updated note is searchable immediately.
The read-only `GET /api/search?q=&type=&page=` endpoint queries it; existing
browse/search pages still read files. `GET /graph` renders the semantic
knowledge graph as a 3D Three.js wireframe-globe (nodes placed on the sphere
surface by PCA of embeddings, colored by theme galaxy with floating galaxy labels
  + a color legend, glowing arcs for edges, alias labels; OrbitControls
drag-rotate + scroll-zoom + auto-rotate; hover, click, type filter, search
highlight; a bottom verb-pill drives three transient modes over the rest state —
  B 时间回放 (nodes fade in by `collected_at` with a scrubber), D 语义漫游 (camera
  auto-tours the edge graph with hook narration + 跨星系 announcements), and E 语义路径
  (pick two stars → client-side Dijkstra over `data.edges` → a drawn glowing path
  line → streamed 中文 explanation));
  `GET /api/graph` serves the raw `{nodes, edges, clusters}` JSON;
  `POST /graph/path` streams the path explanation for E.
`GET /collide` renders the 灵感碰撞 page; `POST /collide/chat` picks a
surprising pair (embedding cosine mid-band) and streams a three-part 中文 synthesis. Initial
deployment must run one `python -m aishelf.db sync --rebuild` to populate all
columns including `note`, backfill embeddings (when `ATLAS_EMBED_*` is
configured) for hybrid `/ask` retrieval, backfill the `edges` table,
the `cluster` column + `clusters` table (theme galaxies) for `/graph`,
`alias` column for `/graph`, and `hook` column for browse lists
(no startup/periodic sync by design).

**Key conventions**

- The site loads `data/` **per request** (small corpus → always fresh; new Hermes
  output shows on refresh, no restart).
- Templates autoescape; scraped URLs pass a `safe_url` (http/https-only) filter.
- Hermes / network calls are **always mocked in tests**; live calls only under
  the `network` pytest marker. Tests live in `tests/unit/` + fixtures in
  `tests/fixtures/contract/`.

## Config

- `AISHELF_DATA_DIR` — where content/notes live (default `data`).
- `AISHELF_DB_PATH` — derived SQLite DB file (default `<data_dir>/atlas.db`).
- `ATLAS_CHAT_BASE_URL` / `ATLAS_CHAT_API_KEY` / `ATLAS_CHAT_MODEL` — the chat
  model that answers `/ask` questions (each defaults to the matching `HERMES_*`).
- `ATLAS_EMBED_BASE_URL` / `ATLAS_EMBED_API_KEY` / `ATLAS_EMBED_MODEL` — a
  self-hosted, OpenAI-compatible embedding service powering `/ask` semantic
  retrieval. **No default** (the chat provider does not serve embeddings); unset
  ⇒ semantic retrieval is silently disabled and `/ask` uses pure FTS5. After
  configuring, run `python -m aishelf.db sync --rebuild` once to backfill
  embeddings; changing the model re-embeds on the next sync.
- `AISHELF_SITE_HOST` / `AISHELF_SITE_PORT` — site bind (default `127.0.0.1:8001`).
- `HERMES_BASE_URL` / `HERMES_API_KEY` / `HERMES_MODEL` — Hermes connection
  (default `http://127.0.0.1:8642/v1`, model `hermes-agent`).
- `AISHELF_COLLECT_ALLOWLIST` — path to the collect passcode allowlist
  (default `config/collect_allowlist.txt`).
- `AISHELF_SCHEDULES` — path to the timed-collection config
  (default `config/schedules.yaml`).
- `AISHELF_SCHEDULER_ENABLED` — `__main__.py` sets it to `1` so the scheduler
  runs alongside the site; set it empty to disable. The test client never sets
  it, so `TestClient` spins up no background thread.
- `ATLAS_BLOG_AUTHOR` — default author name stamped on self-authored posts
  (default `我`).

**Collect access control** (`aishelf.site.allowlist`): `POST /collect/chat` is
gated by a hand-maintained passcode allowlist so only approved callers can spend
the (costly) Hermes collection budget — browsing/notes/delete stay open. The
allowlist is one token per line (`#` comments + blank lines ignored), read **per
request** (edits apply on refresh, no restart). The `/collect` page takes the
passcode and sends it as the `X-Collect-Token` header; an unlisted/empty token
gets a 403 and never touches Hermes. **Fail-closed**: a missing/empty allowlist
denies everyone. Tokens are plaintext over the LAN — enough to stop accidental
collection by LAN visitors, not real auth.

**Scheduled collection** (`aishelf.site.scheduler` + `schedules` +
`schedule_state`): when the site runs, a daemon thread wakes every 60s and runs
any schedule in `config/schedules.yaml` that is due — `enabled`, past today's
`HH:MM`, and not yet run today (per `data/schedule_state.json`). Because Hermes
writes idempotently by id, "collect if updated" is just re-running the saved
prompt via `collect.run_once` (non-streaming). Missed runs (machine asleep at
the time) are caught up on the next tick/startup; a failed run is logged and
left unrecorded so it retries. `due_schedules` is a pure function (the tested
core). The scheduled *runs* bypass the collect passcode (no human to enter it).
Schedules are viewed and edited in the **「定时采集」section of the `/collect`
page** (list + add/edit/toggle/delete), backed by `POST /schedules`,
`/schedules/{name}/toggle`, `/schedules/{name}/delete` — these **mutations are
gated by the collect passcode** (via the shared `_require_collect_token`), since
creating a schedule recurs collection on the Hermes budget. `schedules.save_schedules`
writes the YAML atomically, so file edits and the UI share one source of truth.

`config/authors.example.yaml`, `config/collect_allowlist.example.txt`, and
`config/schedules.example.yaml` are committed templates; the live
`config/authors.yaml`, `config/collect_allowlist.txt`, and
`config/schedules.yaml` are gitignored.

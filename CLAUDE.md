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
- `aishelf/site/` — `app.py` (routes + scheduler lifespan), `views.py` (pure
  filter/search/paginate), `hermes.py` (Hermes connection + robust SSE
  `stream_chat`), `collect.py` (system-prompt builder + non-streaming
  `run_once`), `ask.py` (RAG core for `/ask`: `retrieve`, `build_messages`,
  `source_refs`), `llm.py` (chat-model client, `ATLAS_CHAT_*`,
  `stream_completion`), `notes.py` (per-item notes), `items.py` (`safe_id` +
  `delete_item`), `allowlist.py` (collect passcode gate), `schedules.py`
  (config load + pure `due_schedules`), `schedule_state.py` (last-run dates),
  `scheduler.py` (background `run_due_now` loop), `templates/`, `static/`,
  `__main__.py`.
- `aishelf/db/` — derived SQLite index of the contract files: `config.py`
  (`default_db_path`), `schema.py` (`items` table + FTS5 `items_fts`, plus
  `connect`/`init_db`), `tokenize.py` (CJK bigram `bigrams`/`to_match_query`),
  `sync.py` (idempotent `sync` — upsert + prune), `search.py` (`search` over
  FTS5), `__main__.py` (CLI). The DB is a rebuildable view; files stay the
  source of truth.

**Data & storage** (`data/`, gitignored):

- `data/videos/<id>.json`, `data/blogs/<id>.json` — content records (metadata +
  links only). `data/notes/<id>.json` — user notes (kept separate from records).
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
browse/search pages still read files. Initial deployment must run one
`python -m aishelf.db sync --rebuild` to populate all columns including `note`
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

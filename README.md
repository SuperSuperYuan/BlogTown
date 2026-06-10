# Atlas

A personal, local web app for collecting and browsing AI-domain content —
interview / technical-talk **videos** and **blog / document** articles — with
your own **notes** on each item. Python package: `aishelf`.

Collection is delegated to an external **Hermes** agent (an OpenAI-compatible
API). The two halves are decoupled by a **data contract**: Hermes writes
contract-shaped JSON records into `data/`; the Atlas site reads and renders them.

## Architecture

Three logical pieces (full write-up in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)):

| Piece | Role |
|---|---|
| **Contract** (`aishelf.contract`) | Pydantic models + loader + JSON Schema for the two content modalities — the seam between collection and display. |
| **Site** (`aishelf.site`) | FastAPI + Jinja2 server-rendered app: browse (videos / blogs / search / author), the Hermes collection chat, per-item notes, and delete. |
| **Hermes** (external) | Crawls sources and writes `data/{videos,blogs}/<id>.json` directly, instructed by a system prompt that embeds the JSON Schema. |

Data lives on disk under `data/` (gitignored): `data/videos/<id>.json`,
`data/blogs/<id>.json` for records, `data/notes/<id>.json` for your notes. The
site loads `data/` **per request**, so new Hermes output shows up on refresh
with no restart.

A derived **SQLite + FTS5** index (`data/atlas.db`, also gitignored) mirrors the
contract files and powers CJK-aware full-text search via the read-only
`GET /api/search` endpoint. It's a rebuildable **view** — files stay the source
of truth — synced after each collection and backfillable with
`python -m aishelf.db sync`. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for details.

## Quick start

```bash
pip install -e ".[dev]"
python -m aishelf.site          # serves on http://127.0.0.1:8001
```

Open <http://127.0.0.1:8001> to browse. The **Hermes** tab (`/collect`) is where
you ask the agent to go collect videos / blogs in natural language.

### Collecting via Hermes

Collection runs against your Hermes agent (default `http://127.0.0.1:8642/v1`).
Point Atlas at it with env vars if your endpoint differs:

```bash
export HERMES_BASE_URL=http://127.0.0.1:8642/v1
export HERMES_API_KEY=...        # your Hermes key
export HERMES_MODEL=hermes-agent
```

Because collection is costly, the `/collect/chat` endpoint is gated by a
**passcode allowlist**. Create one and add a token:

```bash
cp config/collect_allowlist.example.txt config/collect_allowlist.txt
# edit it: one passcode per line (# comments and blank lines ignored)
```

Enter the passcode on the Hermes page; it's sent as the `X-Collect-Token`
header and checked on every call. The file is read per request, so edits apply
on refresh — no restart. **Fail-closed:** a missing or empty allowlist denies
everyone. Browsing, notes, and delete are not gated. Note: the passcode is sent
in plaintext, so this guards against accidental LAN triggering, not real attackers.

### Scheduled collection

Atlas can re-run a collection prompt on a daily timer — e.g. "every day at 10:00,
check a blogger for new videos and collect them." Because Hermes writes records
idempotently by id, re-running the prompt simply adds anything new, so there's no
separate update-detection to configure.

You can manage schedules two ways, sharing one `config/schedules.yaml`:

- **From the site** — the **「定时采集」section on the Hermes page** (`/collect`)
  lists schedules and lets you add / edit / enable / delete them. These changes
  require the collect passcode (a schedule recurs collection on the Hermes budget).
- **By editing the file** —

  ```bash
  cp config/schedules.example.yaml config/schedules.yaml
  # edit it: one entry per schedule (name, time "HH:MM", prompt, enabled)
  ```

When you start the site, a background scheduler runs alongside it and fires any
schedule whose time has passed today and that hasn't run yet today. If the
machine was asleep at the scheduled time, the run is caught up on the next start.
A failed run is logged and retried; last-run dates are tracked in
`data/schedule_state.json`.

Scheduled runs **bypass the collect passcode** (no human to enter it) — the
`config/schedules.yaml` file itself is the authorization. Disable the scheduler
by starting with `AISHELF_SCHEDULER_ENABLED=` (empty); point it at another file
with `AISHELF_SCHEDULES=...`.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `AISHELF_DATA_DIR` | `data` | Where content + notes are stored |
| `AISHELF_DB_PATH` | `<data_dir>/atlas.db` | Derived SQLite search index |
| `ATLAS_CHAT_BASE_URL` / `ATLAS_CHAT_API_KEY` / `ATLAS_CHAT_MODEL` | = the matching `HERMES_*` | Chat model that answers `/ask` questions (defaults to the Hermes connection) |
| `AISHELF_SITE_HOST` / `AISHELF_SITE_PORT` | `127.0.0.1` / `8001` | Site bind address |
| `AISHELF_COLLECT_ALLOWLIST` | `config/collect_allowlist.txt` | Collect passcode allowlist |
| `AISHELF_SCHEDULES` | `config/schedules.yaml` | Timed-collection config |
| `AISHELF_SCHEDULER_ENABLED` | `1` (set by launcher) | Run the scheduler; empty to disable |
| `HERMES_BASE_URL` / `HERMES_API_KEY` / `HERMES_MODEL` | `http://127.0.0.1:8642/v1` / — / `hermes-agent` | Hermes connection |

### LAN access

Bind to all interfaces to reach the site from other devices on your network:

```bash
AISHELF_SITE_HOST=0.0.0.0 python -m aishelf.site
```

Then open `http://<your-LAN-ip>:8001` from another device. The site has no real
authentication beyond the collect passcode — keep it on a trusted LAN, not the
public internet.

## Search index

`GET /api/search?q=&type=&page=` serves CJK-aware full-text search from a derived
SQLite + FTS5 index. It's synced automatically after each collection. On a fresh
deploy (or after editing files by hand), backfill or rebuild it:

```bash
python -m aishelf.db sync             # upsert new/changed records, prune deleted
python -m aishelf.db sync --rebuild   # drop + recreate from scratch
```

The DB is a rebuildable view of the files — there's no startup or periodic sync
by design, so run `sync` once after first deploying with existing records.

## Ask your library

`/ask` is a chat that answers questions over your collection — grounded in record
summaries **and your notes** — and links each answer to its sources. Retrieval
uses the same FTS5 index as `/api/search`; answers come from a chat model
configured via `ATLAS_CHAT_*` (defaulting to your Hermes connection, so it works
with no extra config). It is **ungated** (answering is cheap relative to
collection) and multi-turn (history lives in your browser). After saving a note,
the index refreshes so your note becomes searchable.

Because the search index now also covers your notes, an existing deployment must
run `python -m aishelf.db sync --rebuild` once after upgrading so the new note
column is populated.

The answer surfaces two next-action affordances when relevant: if you explicitly
ask to open a video or blog (e.g. "打开那个 RAG 视频"), matching items appear as
**jump-cards** linking to their detail pages; if the library has nothing relevant
to your question, a **「去 Hermes 采集」** guide links to `/collect` with your
question pre-filled (`/collect?q=...`) so you can collect it in one step.

## Export the contract schema

Hermes is instructed with the JSON Schema for content records. Regenerate it
after changing the models:

```bash
python -m aishelf.contract.schema   # writes docs/contract/content-item.schema.json
```

## Tests

```bash
pytest                # default — network/live tests skipped
pytest -m ""          # include live smoke tests (needs a running Hermes)
pytest tests/unit/test_site_app.py::test_home_lists_latest -v   # a single test
```

Hermes / network calls are always mocked in unit tests; live calls only run
under the `network` marker.

## Docs

- Architecture overview: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Design specs and implementation plans: `docs/superpowers/specs/` and
  `docs/superpowers/plans/` (one pair per feature — contract, display site,
  collect page, notes, delete, collect allowlist, scheduled collection,
  derived SQLite DB).

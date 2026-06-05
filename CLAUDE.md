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
- Run tests (network skipped by default): `pytest`
- Run including network smoke tests: `pytest -m ""`
- Run a single test: `pytest tests/unit/test_site_views.py::test_name -v`

## Architecture

Source layout uses a `src/` directory; package is `aishelf`.

- `aishelf/contract/` — `models.py` (`VideoItem`/`BlogItem` discriminated on
  `type`, `parse_item`), `loader.py` (`load_items` — validate + skip-bad + sort),
  `schema.py` (export to `docs/contract/content-item.schema.json`).
- `aishelf/site/` — `app.py` (routes), `views.py` (pure filter/search/paginate),
  `hermes.py` (Hermes connection + robust SSE `stream_chat`), `collect.py`
  (system-prompt builder), `notes.py` (per-item notes), `items.py` (`safe_id` +
  `delete_item`), `templates/`, `static/`, `__main__.py`.

**Data & storage** (`data/`, gitignored):

- `data/videos/<id>.json`, `data/blogs/<id>.json` — content records (metadata +
  links only). `data/notes/<id>.json` — user notes (kept separate from records).
- `id` = `<platform>-<native_id>` (or `blog-<sha1(url)[:12]>`); filename stem
  equals the `id` field.
- **Atomic writes** (`.tmp` + rename) and **id sanitization** (`items.safe_id`,
  the single path-safety choke point) everywhere data is persisted.
- The loader/site **skip and log** a malformed record rather than crashing.

**Key conventions**

- The site loads `data/` **per request** (small corpus → always fresh; new Hermes
  output shows on refresh, no restart).
- Templates autoescape; scraped URLs pass a `safe_url` (http/https-only) filter.
- Hermes / network calls are **always mocked in tests**; live calls only under
  the `network` pytest marker. Tests live in `tests/unit/` + fixtures in
  `tests/fixtures/contract/`.

## Config

- `AISHELF_DATA_DIR` — where content/notes live (default `data`).
- `AISHELF_SITE_HOST` / `AISHELF_SITE_PORT` — site bind (default `127.0.0.1:8001`).
- `HERMES_BASE_URL` / `HERMES_API_KEY` / `HERMES_MODEL` — Hermes connection
  (default `http://127.0.0.1:8642/v1`, model `hermes-agent`).
- `AISHELF_COLLECT_ALLOWLIST` — path to the collect passcode allowlist
  (default `config/collect_allowlist.txt`).

**Collect access control** (`aishelf.site.allowlist`): `POST /collect/chat` is
gated by a hand-maintained passcode allowlist so only approved callers can spend
the (costly) Hermes collection budget — browsing/notes/delete stay open. The
allowlist is one token per line (`#` comments + blank lines ignored), read **per
request** (edits apply on refresh, no restart). The `/collect` page takes the
passcode and sends it as the `X-Collect-Token` header; an unlisted/empty token
gets a 403 and never touches Hermes. **Fail-closed**: a missing/empty allowlist
denies everyone. Tokens are plaintext over the LAN — enough to stop accidental
collection by LAN visitors, not real auth.

`config/authors.example.yaml` and `config/collect_allowlist.example.txt` are
committed templates; the live `config/authors.yaml` and
`config/collect_allowlist.txt` are gitignored.

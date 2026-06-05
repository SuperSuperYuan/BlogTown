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

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `AISHELF_DATA_DIR` | `data` | Where content + notes are stored |
| `AISHELF_SITE_HOST` / `AISHELF_SITE_PORT` | `127.0.0.1` / `8001` | Site bind address |
| `AISHELF_COLLECT_ALLOWLIST` | `config/collect_allowlist.txt` | Collect passcode allowlist |
| `HERMES_BASE_URL` / `HERMES_API_KEY` / `HERMES_MODEL` | `http://127.0.0.1:8642/v1` / — / `hermes-agent` | Hermes connection |

### LAN access

Bind to all interfaces to reach the site from other devices on your network:

```bash
AISHELF_SITE_HOST=0.0.0.0 python -m aishelf.site
```

Then open `http://<your-LAN-ip>:8001` from another device. The site has no real
authentication beyond the collect passcode — keep it on a trusted LAN, not the
public internet.

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
  collect page, notes, delete, collect allowlist).

# Collect Page — Design Spec

**Date:** 2026-06-04
**Status:** Approved (pending spec review)

## Purpose

The third sub-project of the aishelf re-plan: a chat page inside the display
site where the user describes what to collect in natural language, the message
is forwarded to the Hermes agent, and Hermes crawls the requested resources and
**writes contract-conforming records directly into `data/`**. The existing
display pages then show the new content on refresh.

Depends on:
- `src/aishelf/contract/` and `docs/contract/content-item.schema.json` (the contract).
- `src/aishelf/site/` (the display site, gets a new page).

## Decisions (locked during brainstorming)

- **Hermes writes files directly** ("situation one"): Hermes runs on the same
  machine with filesystem access to this repo's `data/`. The backend only
  proxies the chat and tells Hermes the absolute `data/` path + the contract; it
  does not parse or persist records itself.
- **Chat lives in the display site**, not a standalone app. The old standalone
  `src/aishelf/webui/` is **deleted** (chat capability moves into `aishelf.site`).
- **Restyle:** the chat page matches the display site's visual language (same
  topbar, rounded cards, `#0a84ff` accent), replacing the old bare webui look.

## Scope

In scope: a `/collect` chat page in `aishelf.site`; an SSE proxy endpoint to
Hermes; a system-instruction builder that hands Hermes the data path + JSON
Schema + write conventions; nav entry; deletion of the old `webui` package.

Out of scope (YAGNI): backend re-validation of files Hermes wrote (the loader
already skips invalid files); collection history / task queue / scheduling;
auth; pushing live updates to the browser (the user refreshes the section pages).

## Architecture

```
Browser  /collect (chat page)
   │  POST /collect/chat  { messages: [...] }
   ▼
aishelf.site backend
   ├─ collect.build_collection_instructions(data_dir, schema_path)  → system message
   │     (absolute data path + embedded JSON Schema + id/atomic-write rules)
   ├─ hermes.stream_chat([system, *messages])   → openai SDK, stream=True
   ▼
Hermes agent (127.0.0.1:8642)
   ├─ crawls the requested sources
   └─ writes <data>/videos/<id>.json and <data>/blogs/<id>.json itself
   │  (token narration streamed back)
   ▼ SSE (data: {delta|error|done}) → browser
Later: user opens /videos or /blogs → loader reads data/ → new content shown
```

## Components / Files

- `src/aishelf/site/hermes.py` — Hermes connection + robust SSE streaming.
  - `get_settings()` / `get_client()` reading `HERMES_BASE_URL` (default
    `http://127.0.0.1:8642/v1`), `HERMES_API_KEY`, `HERMES_MODEL` (default
    `hermes-agent`).
  - `stream_chat(messages) -> Iterator[str]` — yields SSE strings
    `data: {json}\n\n` with `{"delta": ...}` / `{"error": ...}` / `{"done": true}`.
    Skips chunks whose `choices` is empty/None; converts `APIConnectionError`,
    `APIStatusError`, `APIError`, and any other exception into a single error
    event (carried over from the webui fix — never breaks the stream silently).
- `src/aishelf/site/collect.py` — `build_collection_instructions(data_dir, schema_path) -> str`,
  a pure function returning the system instruction text.
- `src/aishelf/site/app.py` — add `GET /collect` (serves the page) and
  `POST /collect/chat` (SSE proxy; prepends the system instruction to the
  posted messages).
- `src/aishelf/site/templates/collect.html` — the chat page, extending `base.html`.
- `src/aishelf/site/templates/base.html` — add a「采集」nav link.
- `src/aishelf/site/static/style.css` — add chat styles consistent with the site.
- **Delete:** `src/aishelf/webui/` (whole package), `tests/unit/test_webui.py`,
  `tests/integration/test_webui_network.py`. (`scripts/test_hermes.py` stays — a
  handy standalone connectivity check.)

## The Collection Instruction (`build_collection_instructions`)

Returns a system message that tells Hermes, in concrete terms:

- **Where to write:** the absolute path `get_data_dir().resolve()`; videos go to
  `<data>/videos/<id>.json`, blogs to `<data>/blogs/<id>.json`. It must create
  these directories if missing.
- **Format:** the full JSON Schema, read verbatim from
  `docs/contract/content-item.schema.json` and embedded in the message, as the
  authoritative record shape.
- **id rule:** `<platform>-<native_id>` (e.g. `youtube-<videoId>`,
  `bilibili-<bvid>`); for blogs with no native id, `blog-<sha1(source_url)[:12]>`.
  The filename stem equals the `id` field.
- **Atomic write:** write `<id>.json.tmp` then rename to `<id>.json`. Re-collecting
  the same item overwrites (idempotent).
- **Content rules:** videos store metadata + links only (incl. `thumbnail_url`,
  and `embed_url` when available); blogs store a summary + link. Hermes generates
  `summary` and `keywords` itself.
- **Wrap-up:** after writing, report in prose which items were written.

This function is pure and unit-testable (no network): given a data dir and the
schema path, assert the returned text contains the absolute data path, both
subdirectory paths, and key field names from the schema.

## Chat Page UX

- Extends `base.html`, so it shares the site topbar (with the new「采集」link
  active) and styling.
- A lead line: "描述你想采集的内容，例如：爬取 Karpathy 最近的视频".
- Message log with distinct user/assistant bubbles; assistant text fills in
  token-by-token from the SSE stream; errors render as a red bubble. Conversation
  history kept client-side and sent in full each turn (Hermes is stateless across
  requests; the backend re-prepends the system instruction each time).
- Below the input, persistent buttons「查看视频」→ `/videos` and「查看博客」→
  `/blogs` (the site re-reads `data/` per request, so a refresh shows new content).

## Error Handling

- SSE stream never crashes silently: connection failure, HTTP error status, and
  any unexpected exception each emit one `{"error": ...}` event and stop.
- Empty `messages` → HTTP 400.

## Testing

All tests mock Hermes / never hit the network.

- **`collect.py`:** `build_collection_instructions` output contains the absolute
  data path, `videos`/`blogs` subdirs, the atomic-write rule, and key schema
  field names (e.g. `summary`, `keywords`, `thumbnail_url`).
- **`hermes.py`:** mocked client — streams `delta` events then `done`; skips a
  `choices=None` chunk without crashing; connection error yields an error event.
- **Routes:** `GET /collect` returns 200 HTML containing the chat page; the「采集」
  nav link appears on site pages. `POST /collect/chat` with a mocked Hermes client
  streams `delta` + `done`; empty `messages` → 400.
- **Deletion:** the old `tests/unit/test_webui.py` and
  `tests/integration/test_webui_network.py` are removed; the suite still passes.

## Success Criteria

- The old `src/aishelf/webui/` package is gone; the full suite passes.
- `python -m aishelf.site` serves `/collect`, styled consistently with the site.
- Posting a message streams Hermes's response token-by-token; an unreachable
  Hermes shows an error bubble (no hang).
- The instruction handed to Hermes contains the absolute `data/` path and the
  contract schema, so Hermes can write conforming files that the display pages
  then render.

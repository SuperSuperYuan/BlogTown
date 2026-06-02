# Hermes WebUI — Design Spec

**Date:** 2026-06-02
**Status:** Approved (pending spec review)

## Purpose

A local web page that lets the user chat with their Hermes agent to get work
done (e.g. "帮我爬某个 up 主的视频"). The user types a request, it is forwarded to
the Hermes agent, and the reply streams back into the page with a typewriter
effect.

Hermes is reachable as an OpenAI-compatible API server at
`http://127.0.0.1:8642/v1` (model `hermes-agent`). Connectivity is already
verified via `scripts/test_hermes.py`.

## Scope

In scope:

- A single-page chat UI (one conversation, history kept client-side).
- A thin FastAPI backend that proxies chat requests to Hermes and streams the
  response back.

Explicitly out of scope (YAGNI — may be added later):

- Multi-conversation management / persistence.
- Authentication / multi-user.
- A scrape-specific structured task form (the user chose a plain chat UI).

## Architecture

Three layers; the backend exists mainly to keep the API key off the browser and
to avoid browser→localhost CORS issues.

```
Browser (index.html)
   │  POST /api/chat  { messages: [...] }
   ▼
FastAPI backend (app.py)   ← API key lives here only, read from env
   │  openai SDK, stream=True
   ▼
Hermes  http://127.0.0.1:8642/v1
   │  streamed chunks
   ▼ (SSE: text/event-stream) token-by-token back to the browser
```

## Components

### `src/aishelf/webui/app.py` — FastAPI application

- `GET /` → serves the static `index.html`.
- `POST /api/chat` → accepts the full conversation history
  (`{"messages": [{"role": ..., "content": ...}, ...]}`), calls Hermes via the
  `openai` SDK with `stream=True`, and relays each delta to the browser as a
  Server-Sent Events stream (`Content-Type: text/event-stream`).
  - Each SSE `data:` line carries one token/delta. A terminal sentinel event
    (e.g. `data: [DONE]`) marks completion.
  - On `APIConnectionError` / `APIStatusError`, emit a single SSE error event so
    the frontend can render an error bubble instead of hanging.
- Configuration is read from environment variables, reusing the names already
  established by `scripts/test_hermes.py`:
  - `HERMES_BASE_URL` (default `http://127.0.0.1:8642/v1`)
  - `HERMES_API_KEY` (default: the local dev key)
  - `HERMES_MODEL` (default `hermes-agent`)
- The API key is never sent to the browser.

### `src/aishelf/webui/static/index.html` — single-file frontend

- Plain HTML + CSS + vanilla JS, no build step.
- Chat history area + input box + send button.
- On send: append the user message locally, POST the full `messages` array to
  `/api/chat`, then read the SSE stream and append tokens to the assistant
  bubble live.
- Conversation history is held in browser memory and sent in full on each
  request (Hermes is stateless across requests).

### `src/aishelf/webui/__main__.py` — entry point

- Allows `python -m aishelf.webui` to launch uvicorn on a default port (8000),
  as an alternative to invoking `uvicorn aishelf.webui.app:app` directly.

## Data Flow

1. User types a message and clicks send.
2. Browser appends it to local history and POSTs `{messages}` to `/api/chat`.
3. FastAPI calls Hermes with `stream=True`.
4. Hermes streams chunks; FastAPI relays each as an SSE `data:` event.
5. Browser appends each delta to the current assistant bubble; on `[DONE]` the
   turn ends and the assistant message is committed to local history.

## Error Handling

- **Connection failure** (`APIConnectionError`): SSE error event → frontend
  shows "无法连接 Hermes，请确认服务在运行" bubble. Page stays usable.
- **Service error** (`APIStatusError`): SSE error event including the status
  code → frontend shows an error bubble. Page stays usable.
- **Empty / malformed request**: backend returns 400 with a JSON error.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `HERMES_BASE_URL` | `http://127.0.0.1:8642/v1` | Hermes OpenAI-compatible endpoint |
| `HERMES_API_KEY` | local dev key | Bearer token |
| `HERMES_MODEL` | `hermes-agent` | Model name |

## Dependencies

- Add `fastapi` and `uvicorn[standard]` to `pyproject.toml`.
- `openai` is already a dependency.

## Running

```bash
uvicorn aishelf.webui.app:app --port 8000
# or
python -m aishelf.webui
```

Then open `http://127.0.0.1:8000` in a browser.

## Testing

Following the project rule that Hermes/network calls are always mocked in unit
tests:

- **Unit:** test `POST /api/chat` with a mocked `openai` client — assert the SSE
  stream contains the expected `data:` deltas and terminal sentinel, and that
  the error path emits an error event. Use FastAPI's `TestClient`.
- **Network smoke (under the `network` marker):** a single live call against the
  running Hermes server, skipped by default.

## Success Criteria

- `python -m aishelf.webui` starts the server with no errors.
- Opening the page shows a chat box.
- Typing a request and sending it streams Hermes's reply token-by-token into the
  page.
- Killing the Hermes server produces a visible error bubble, not a hang or a
  blank page.
- Unit tests pass with Hermes mocked.

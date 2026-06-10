# Ask-your-library (RAG chat) — Design

**Date:** 2026-06-09
**Status:** Approved, ready for implementation plan
**Package:** `aishelf` (product: Atlas)

## 1. Summary

A `/ask` chat that answers natural-language questions over the user's collected
library — grounded in the contract records' **summaries** plus the user's
**personal notes** — using retrieval over the derived `atlas.db` and a chat LLM.
Answers stream back as prose with `[n]` citations and a linked **Sources** list
pointing at the items. This turns Atlas from a *browser* of content into a
*queryable second brain*.

It reuses three things Atlas already has: the FTS5 search layer (`aishelf.db`),
the robust OpenAI-compatible SSE streaming pattern (`aishelf.site.hermes`), and
the existing chat UI styling from `/collect`.

## 2. Goals / non-goals

**Goals**
- Ask questions in natural language and get answers grounded *only* in the user's
  own library (summaries + notes), with citations linking back to each item.
- Multi-turn conversation: follow-up questions work; each turn re-retrieves using
  the latest question.
- Notes are first-class for retrieval — a thought the user wrote can surface its
  item even if the item summary doesn't mention the term.
- No hallucination: when retrieval finds nothing relevant, the assistant says it
  has nothing in the library on that topic rather than inventing an answer.

**Non-goals (YAGNI for v1)**
- Embeddings / semantic retrieval — FTS5 is the v1 retriever (semantic search is
  a separate, future idea).
- Full-text / video-transcript fetching at answer time (separate idea).
- Server-side persistence of conversations (per-browser only, like `/collect`).
- Re-ranking, query rewriting, or agentic multi-step retrieval.
- Access control on `/ask` — it is ungated (see §7).

## 3. Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Answer LLM | **Separate chat-model config**, defaulting to the Hermes connection but overridable | Hermes is a costly, agentic *collection* model; answering should be able to point at a cheap/fast chat model. |
| Grounding corpus | **Summaries + user notes** | Notes capture the user's own thinking — core to a "second brain". |
| Note retrieval | **Approach A** — fold notes into the FTS index | Makes notes first-class for recall; stays a rebuildable derived view. |
| Conversation | **Multi-turn** with follow-ups | Natural for exploration; modest added complexity. |
| Access control | **Ungated**, like browsing/notes | Answering is cheap relative to collection and is core "reading" use. |
| Retriever | **FTS5 (existing)** | Reuses the shipped search layer; embeddings are a later, separate layer. |

## 4. Architecture

### 4.1 Flow

```
question + prior turns
        │
        ▼
 retrieve(db_path, question, k)         ── FTS5 MATCH over summaries + notes
        │  top-K hits (+ each hit's note text loaded from disk, always fresh)
        ▼
 build_messages(question, history, hits) ── grounded system prompt:
        │                                    numbered sources, citation rules,
        │                                    "answer only from sources, else say so"
        ▼
 stream_completion(messages)            ── chat LLM, SSE deltas (robust, never
        │                                    breaks the stream)
        ▼
 browser renders streamed prose + a Sources list (links to /videos|/blogs/{id})
```

### 4.2 New / changed units

| Unit | Responsibility | Depends on |
|---|---|---|
| `aishelf.site.llm` (new) | `get_chat_settings()` reading `ATLAS_CHAT_BASE_URL` / `ATLAS_CHAT_API_KEY` / `ATLAS_CHAT_MODEL` (each defaulting to the corresponding Hermes setting); `stream_completion(messages) -> Iterator[str]` — a generic, robust SSE streamer (same error-to-SSE-event discipline as `hermes.stream_chat`). | `openai`, `hermes` (for defaults), env |
| `aishelf.site.ask` (new) | The RAG core, pure/testable. `retrieve(db_path, question, *, k)` → list of hits each carrying its note text (loaded via `notes.load_note`, always fresh). `build_messages(question, history, hits)` → `list[dict]` chat messages: a grounded system prompt (numbered sources block, citation instructions, no-source guard), the prior turns, and the new question. | `db.search`, `notes` |
| `aishelf.db.schema` | Add a `note` column to the `items_fts` FTS5 table (FTS-only; not selected into `SearchHit`). | — |
| `aishelf.db.sync` | When upserting an item, read its note from disk (if any) and include the note text in the item's FTS document. A full rebuild reconstructs notes from files. | `notes` |
| `app.py` note route | After `save_note` succeeds, the **`/notes/{id}` route** (not `notes.py` — kept dependency-free) triggers an off-thread DB sync so the note becomes searchable promptly, reusing the shared `_sync_db_async` helper that also runs after collection. *As built:* this is the full idempotent `sync` (hash-diffed, so unchanged items skip re-indexing), chosen for simplicity given the small per-request-loaded corpus rather than a single-item fast path. Failure to sync is logged, never breaks saving the note (the note file is the source of truth; a rebuild recovers the index). | `db.sync` |
| `app.py` | `GET /ask` — render the chat page. `POST /ask/chat` — accept `{messages}` (conversation), retrieve, build, and stream via `llm.stream_completion`. **Ungated.** | `ask`, `llm` |
| `templates/ask.html` + nav link | A chat page reusing the `/collect` chat styling; a nav link to `/ask`; a streamed answer area; a **Sources** list rendered client-side from the `{sources}` SSE event, each item a link to `/videos/{id}` or `/blogs/{id}`. | existing templates |

### 4.3 The grounded prompt (shape)

`build_messages` produces, in order:
1. A **system** message: the assistant answers questions about *the user's
   personal AI-content library*; it must use **only** the numbered sources
   provided; cite claims as `[n]` referring to those sources; if the sources do
   not contain the answer, it must say it has nothing in the library on that
   topic (and may suggest collecting more). Answers in the user's language
   (Chinese-friendly).
2. The numbered **sources block** (embedded in the system message or a leading
   context message): for each hit, `[n] <title> — <author>, <platform>` then its
   summary and, if present, the user's note (clearly labelled as the user's own
   note). Each source maps to an item id so the frontend can link it.
3. The prior conversation **history** (user/assistant turns) as given by the client.
4. The new **user** question.

The exact wording is an implementation detail; the spec fixes the *contract*:
sources are numbered, citations reference those numbers, and the no-source guard
is mandatory.

## 5. Routes

| Method & path | Purpose |
|---|---|
| `GET /ask` | Render the Ask chat page (reuses chat styling; per-browser history). |
| `POST /ask/chat` | Body `{messages: [...]}`. Retrieve top-K for the latest user message, build the grounded prompt, stream the answer as SSE (`{delta}` / `{error}` / `{done}`), plus a `{sources}` event (or embedded payload) so the client can render the linked Sources list. **Ungated.** |

SSE event shape matches the existing `/collect/chat` contract (`hermes.sse`):
`{"delta": "..."}`, `{"error": "..."}`, `{"done": true}`. A `{"sources": [...]}`
event is emitted once (before or after the deltas) listing the cited items
(`id`, `type`, `title`, `author`) for the Sources panel.

## 6. Data & config

- **No new data files.** Retrieval reads `atlas.db` (FTS5) and notes from
  `data/notes/<id>.json`. Conversation history lives only in the browser
  (localStorage), like `/collect`.
- **New env vars** (each defaults to the matching Hermes setting, so zero config
  works out of the box):
  - `ATLAS_CHAT_BASE_URL` (default = `HERMES_BASE_URL`)
  - `ATLAS_CHAT_API_KEY` (default = `HERMES_API_KEY`)
  - `ATLAS_CHAT_MODEL` (default = `HERMES_MODEL`)
- **DB schema bump:** `items_fts` gains a `note` column. Because the DB is a
  derived, rebuildable view, deployment runs `python -m aishelf.db sync
  --rebuild` once to pick up the new column for existing records (documented in
  README/ARCHITECTURE).

## 7. Cross-cutting concerns

- **No hallucination:** the system prompt forbids answering outside the provided
  sources; empty retrieval ⇒ an explicit "nothing in your library on that" reply.
- **Robust streaming:** `llm.stream_completion` turns any LLM/connection error
  into an SSE `{error}` event and never breaks the stream — identical discipline
  to `hermes.stream_chat`.
- **XSS:** answer text is rendered as text (escaped); Sources links are built
  from validated item ids (`/videos/{id}` / `/blogs/{id}`) — ids already pass
  `safe_id` on the data path; the frontend links by id + type only.
- **Notes stay the source of truth:** the FTS `note` column is derived; a note
  save updates the file atomically (unchanged) and best-effort re-syncs the
  index. A failed re-sync only delays searchability until the next sync/rebuild.
- **Ungated, LAN-only:** consistent with the existing "keep Atlas on a trusted
  LAN" posture; `/ask` spends LLM tokens but is treated as read/use, not collect.

## 8. Testing (TDD; LLM always mocked)

- `aishelf.site.ask.retrieve` over a fixture `atlas.db`: returns top-K hits;
  a **note-only match** (term appears only in the note, not the summary) surfaces
  its item — proving notes are indexed (Approach A).
- `aishelf.site.ask.build_messages` (pure): asserts the numbered sources block,
  the prior history, the new question, the citation instruction, and the
  no-source guard are all present and ordered correctly.
- `aishelf.db.sync`: after saving a note for an item, syncing makes the item
  findable by a term that appears only in the note.
- `POST /ask/chat` via `TestClient` with a **mocked** chat client: happy path
  (streams deltas + a sources event + done), LLM error → `{error}` event,
  empty-corpus question → the assistant's "nothing in your library" path.
- Nav/template smoke: `GET /ask` renders; a nav link to `/ask` exists.
- Network/live LLM calls only under the `network` marker, never in default runs.

## 9. Rollout

1. Implement behind the normal flow (no feature flag needed — additive).
2. `python -m aishelf.db sync --rebuild` once after deploy to populate the new
   `note` FTS column for existing records.
3. Update README + ARCHITECTURE: new `/ask` + `/api`-adjacent route, the
   `ATLAS_CHAT_*` env vars, and the rebuild note.

## 10. Open questions

None blocking. Future extensions (explicitly out of scope here): embeddings/
hybrid retrieval, full-text/transcript grounding, and server-side conversation
history.

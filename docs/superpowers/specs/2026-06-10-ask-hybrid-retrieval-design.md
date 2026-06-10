# Ask Hybrid Retrieval — FTS5 + self-hosted embeddings

**Date:** 2026-06-10
**Status:** Design (approved, pre-plan)
**Scope:** `/ask` retrieval only. `/search` and `/api/search` keep their current
FTS5 path unchanged.

## Problem

`/ask` retrieval uses OR-mode FTS5 (bigram). It matches only on shared character
bigrams, so it has two gaps:

1. **No semantics / cross-lingual recall.** A Chinese question won't match an
   English talk that covers the same topic (no shared bigrams), and synonyms /
   paraphrases are missed entirely.
2. **Loose tail.** OR-mode lets an item in on a single common bigram. We already
   prune that tail with a bigram-overlap floor (`relevant_sources`,
   `RELEVANCE_FLOOR = 0.15`), but the floor can't *add* semantically-relevant
   items FTS5 never surfaced.

A vector/semantic retrieval path fixes both. Embeddings come from a
**self-hosted embedding service** exposed as an OpenAI-compatible
`/v1/embeddings` endpoint (e.g. vLLM / TEI / Infinity / Ollama serving a
bge / e5 model). DeepSeek (the chat model) does not offer embeddings, so the
embedding service is a separate provider with no default.

## Decisions (locked)

- **Scope:** `/ask` retrieval only.
- **Fusion:** hybrid — vector is the primary relevance signal, FTS5 is a safety
  net for exact terms / rare proper nouns / ids; candidates are merged and
  re-ranked by cosine similarity, then floored.
- **Embedding source:** self-hosted, OpenAI-compatible `/v1/embeddings`,
  configured via `ATLAS_EMBED_*`. **No default — unset ⇒ feature silently
  disabled, pure FTS5** (current behavior).
- **Storage / search:** embeddings stored as a BLOB column in `atlas.db`;
  brute-force cosine over the corpus in numpy (no vector DB). The corpus is a
  personal library (hundreds–low-thousands of items), so exhaustive cosine is
  sub-100 ms.
- **New dependency:** `numpy` (cosine math only; vector (de)serialization uses
  the stdlib `array` module). Accepted.
- **Graceful degradation:** any embedding failure (unconfigured, unreachable,
  error) falls back to the existing pure-FTS5 + `relevant_sources` path. Reads
  never crash — consistent with Atlas's resilience convention.

## Architecture

The contract files stay the source of truth; `atlas.db` stays a derived,
rebuildable view. Embeddings are part of that derived view, computed at sync
time and recomputed on `sync --rebuild`.

### New / changed modules

| Module | Responsibility |
|---|---|
| **`aishelf/embed.py`** (new, package root) | Embedding client. OpenAI-compatible, reads `ATLAS_EMBED_BASE_URL/_API_KEY/_MODEL`. API: `embed_texts(texts) -> list[list[float]] \| None`, `embed_query(text) -> list[float] \| None`, `is_configured() -> bool`, `model_name() -> str \| None`. Returns `None` (never raises to caller) when unconfigured or on any client/HTTP error, so callers degrade. Placed at the package root because both `db` and `site` use it (avoids a `db → site` reverse dependency). Reuses the `openai` SDK, mirroring `llm.py` / `hermes.py`; mocked in tests the same way. |
| **`aishelf/db/vector.py`** (new) | Pure vector math over stored embeddings. `pack(vec) -> bytes` / `unpack(blob, dim) -> list[float]` (stdlib `array('f')`). `load_embeddings(db_path, *, type=None) -> tuple[list[str], np.ndarray]` (ids + matrix of rows that have an embedding). `cosine_search(query_vec, ids, matrix, *, top_n) -> list[tuple[str, float]]` (cosine similarity, descending). No I/O beyond the read; deterministic and unit-testable. |
| `aishelf/db/schema.py` | `items` table gains three nullable columns: `embedding BLOB`, `embedding_model TEXT`, `embedding_dim INTEGER`. Reflected in `init_db`. Existing deployments run `python -m aishelf.db sync --rebuild` once to add them (same procedure used when the `note` column was added). |
| `aishelf/db/sync.py` | When `embed.is_configured()`, after the row's text is assembled, recompute its embedding iff it is **missing**, the **stored model differs** from the configured model, or the **embedded text changed**. Persist `embedding`, `embedding_model`, `embedding_dim`. When not configured, or when `embed_texts` returns `None`, skip embeddings (log once) — FTS5 sync proceeds unchanged. The embedded text is the same composite used for relevance today: `title + summary + keywords + author + note`. |
| `aishelf/site/ask.py` | `retrieve()` becomes hybrid (below). The pure helpers (`relevant_sources`, `_overlap`, `is_low_confidence`) are unchanged and remain the degraded-path scorer. |

### `retrieve()` — hybrid flow

Constants (in `ask.py`): `SIMILARITY_FLOOR` (cosine threshold, e.g. `0.30` —
tuned during implementation), `CANDIDATE_N` (per-path candidate pool, e.g. `20`),
final `k = DEFAULT_K` (≈6).

1. `qv = embed.embed_query(question)`.
2. **If `qv is None`** (unconfigured / service down): fall back to the **current**
   path — OR-mode FTS5 → `relevant_sources(question, sources)`. Behavior identical
   to today. Stop.
3. **Vector recall:** `vector.load_embeddings(db_path)` + `cosine_search(qv, …,
   top_n=CANDIDATE_N)` over the **whole corpus** (not just FTS5 hits — this is what
   surfaces items FTS5 missed).
4. **FTS5 recall:** existing OR-mode `db_search.search(..., mode="or",
   limit=CANDIDATE_N)` — the exact-term safety net.
5. **Merge & rank:** union the two id sets, then:
   - Items **with** an embedding get a cosine score; **keep** those with
     `cosine >= SIMILARITY_FLOOR`, ranked by cosine descending.
   - **Plus** FTS5 exact hits (safety-net direct-include) even if below the floor
     or — in a partially-synced corpus — lacking an embedding entirely; these
     append after the cosine-ranked block, in FTS5 (bm25) order.
   - Cap the combined list at `k`, preserving that order.
6. Hydrate the kept ids into `Source` objects (with notes, as today) and return.

`source_refs`, `build_messages`, `nav_*`, and `is_low_confidence` are unchanged —
they consume whatever `retrieve()` returns. `is_low_confidence` still guards the
empty→collect path; on the hybrid path an empty result (nothing cleared the floor
and no FTS5 hits) still reads as low-confidence.

### Config

- `ATLAS_EMBED_BASE_URL`, `ATLAS_EMBED_API_KEY`, `ATLAS_EMBED_MODEL` — the
  self-hosted embedding service. **No fallback to Hermes/chat** (unlike
  `ATLAS_CHAT_*`); unset ⇒ disabled.
- Documented in `CLAUDE.md` and `docs/ARCHITECTURE.md` alongside the existing
  `ATLAS_CHAT_*` block, including the silent-disable semantics and the
  `sync --rebuild` backfill step.

### Operational notes

- **Backfill:** one `python -m aishelf.db sync --rebuild` after configuring
  `ATLAS_EMBED_*` populates all embeddings. Same as the `note`-column rollout.
- **Incremental:** every sync (post-collection, off-thread post-note-save) only
  re-embeds changed / new / model-mismatched rows, so the common note-save sync
  stays cheap.
- **Model change:** changing `ATLAS_EMBED_MODEL` makes stored `embedding_model`
  mismatch on the next sync, triggering re-embed; `--rebuild` forces a full
  recompute.
- **Latency:** `/ask` adds one query-embedding round-trip (local service, tens of
  ms) before the existing LLM stream. Negligible.

## Testing (network always mocked; live only under the `network` marker)

- **`embed.py`:** monkeypatch the client — assert request shape (model + input
  list), `None` when unconfigured, `None` on client/HTTP error (never raises).
- **`db/vector.py`:** pure unit tests — `pack`/`unpack` round-trip; `cosine_search`
  ordering on known vectors; correct top-n; ignores rows without embeddings;
  handles a dimension mismatch gracefully (skip/log, don't crash).
- **`db/sync.py`:** inject a fake embedder — embeddings persisted with model+dim;
  skipped when not configured; re-embedded when the stored model differs;
  re-embedded when the text changed; not re-embedded when unchanged.
- **`ask.retrieve` (hybrid):** inject fake query/item embeddings —
  (a) an item FTS5 misses is recalled by the vector path;
  (b) an FTS5 exact hit below the cosine floor is still included (safety net);
  (c) a below-floor, non-FTS5 item is pruned;
  (d) `embed_query → None` falls back to the exact current pure-FTS5 behavior
      (regression-locks today's output).

## Out of scope (YAGNI)

- Vector search in `/search` / `/api/search` (FTS5 stays).
- A real vector database / ANN index (brute-force cosine suffices at this scale).
- Re-ranking models, MMR diversity, query expansion.
- Chunking long documents (records store summaries/metadata, not full bodies).
- Auto-detecting embedding dimension changes beyond the stored-model check.
- A default embedding provider (none exists for the current stack).

## Risks & mitigations

- **Embedding service unavailable** → graceful fallback to pure FTS5 (designed in,
  test (d) locks it).
- **`SIMILARITY_FLOOR` mis-tuned** → single constant, easy to dial; FTS5 safety
  net means a too-high floor still returns exact hits.
- **Stale embeddings after manual file edits** → same caveat as the rest of the
  derived DB; `sync` / `--rebuild` fixes it (documented).
- **numpy dependency** → accepted; isolated to `db/vector.py`.

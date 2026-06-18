# AI 笔记草稿 (AI-drafted note) — Design

**Date:** 2026-06-18
**Status:** Approved (autonomous-iteration; author = approver, rationale logged inline)

## Why

Every Atlas feature so far is **read or synthesis** (钩子, 灵感碰撞, 今日速读, 藏书镜,
图谱, 问答). None help you **write**. Yet notes are the one place the user adds
their own value — and notes are already indexed into FTS5 + fed to `/ask` RAG, so
a richer note pool makes the *whole library* smarter. The friction of starting a
note from a blank box is exactly what keeps most items note-less.

「AI 笔记草稿」adds the first **write-assist** capability: a 「✨ AI 起草」button in
the note editor streams a short draft **skeleton** — 要点 / 为什么值得记 / 待探索 —
built from the item's metadata, into the textarea. The user edits it and saves
through the existing save path. The AI gives you something to react to instead of
a blank page; you stay the author.

Fits the project taste (简洁 + 实用 + 好玩，拒绝花里胡哨; distill rather than
decorate; reuse the existing LLM client + note editor). **好玩** = the AI riffing
on your content (content-surprise, not visual gimmickry). **实用** = lower the
cost of the highest-value user action, which compounds into search/RAG. Same
on-demand, no-persistence, no-new-config shape as `/collide` and `/mirror`.

## What it is

- A 「✨ AI 起草」button inside the note editor (`_note_editor.html`), in the edit
  area's `.note-bar` next to 「保存笔记」.
- `POST /notes/{id}/draft` loads the item (per-request file model) and **streams**
  a Markdown draft via `llm.stream_completion`. Ungated (cheap synthesis, like
  `/ask`/`/collide`/`/mirror` — not the Hermes path).
- The draft streams **into the textarea**. It is NOT auto-saved — the user reviews,
  edits, and clicks 「保存笔记」(existing `POST /notes/{id}`). The user owns the note.

### The draft (LLM output)

Markdown (notes already render Markdown via `markdown.render_markdown`), concise,
honest that it is a scaffold from metadata (not a fake full summary):

```
## 要点
- …（3-5 条，从摘要/关键词提炼的核心点）

## 为什么值得记
…（1-2 句，这条内容对“我”可能的价值/独特角度）

## 待探索
- …（2-3 个这条内容引出但未回答的问题）
```

## Architecture — mirrors `collide.py` / `path.py` / `mirror.py`

New leaf module `src/aishelf/site/notedraft.py` — pure prompt builder only (no DB,
no LLM). The route does the item lookup (reusing existing app helpers) and the
streaming.

```python
build_messages(item: dict, existing_note: str = "") -> list[dict]   # pure
```

- `item` is the dict shape produced by the existing `app._item_dict(it)`
  (`title`, `summary`, `keywords`, `author`, `type`).
- `existing_note`: when the user already has note text, it's passed so the draft
  *complements* rather than repeats it (the prompt says "在已有笔记之外补充，不要
  重复"). Empty string when starting fresh.

System prompt: a concise 中文 note-taking assistant; output the three Markdown
sections above; honest scaffold-from-metadata framing; plain Markdown only; no
preamble/closing. User message: the item's title/type/author/summary/keywords,
plus the existing note when non-empty.

### Route wiring (`app.py`)

```python
@app.post("/notes/{item_id}/draft")
def note_draft(item_id: str):
    # Ungated: drafting is cheap (like /ask, /collide, /mirror), not the Hermes path.
    try:
        items.safe_id(item_id)
    except ValueError:
        raise HTTPException(status_code=404)
    it = next((x for x in _items() if x.id == item_id), None)
    if it is None:
        raise HTTPException(status_code=404)
    existing = _note_for(it)

    def _gen():
        yield from llm.stream_completion(
            notedraft.build_messages(_item_dict(it), existing)
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

Reuses `items.safe_id`, `_items()`, `_note_for`, `_item_dict`, `llm`,
`StreamingResponse` — all already imported/defined (the same set `/api/item/{id}`
and `/mirror/chat` use). `notedraft` added to the `aishelf.site` import block.

`llm.stream_completion` already yields `{"delta": …}` events and a final
`{"done": true}`, and converts an unconfigured/unreachable chat model into an
`{"error": …}` event — so the unconfigured case degrades gracefully with no extra
code (same as `/mirror`).

### Frontend (`_note_editor.html`)

Add a `「✨ AI 起草」` button (`id="note-draft"`) in `.note-bar` before/after
「保存笔记」. Its click handler:

- disables itself + shows status 「正在起草…」;
- `fetch('/notes/{id}/draft', {method:'POST'})`, reads the SSE stream with the
  same delta-reader loop used by `collide.html`/`mirror.html`;
- **streams into the textarea**: if the textarea is non-empty when drafting
  starts, append after a blank-line separator; otherwise fill from empty. (Track
  a base value at start; set `ta.value = base + accumulated`.)
- on `{"error"}` → show 「⚠️ …」in the status span; re-enable the button in a
  `finally`.
- The draft is left in the textarea for the user to edit; **no auto-save**.

The button lives in the edit area (`#note-edit`), which is shown by default when
there is no note yet (the common case) and via 「编辑」otherwise — so it's reachable
in both states. All status text via `textContent`; no innerHTML from stream data
(it goes into `textarea.value`, inherently inert).

### Styling

Reuse existing `.btn`/`.btn-link`/`.note-status` classes; the new button can use
`.btn-link` (secondary) so 「保存笔记」stays the primary action. Minimal/no new CSS.

## Error handling

- Unknown/unsafe id → 404 (`safe_id` guard + `_items()` lookup), same as
  `/api/item/{id}`.
- Chat model unconfigured/unreachable → `llm.stream_completion` yields
  `{"error": …}` + `{"done": true}`; the editor shows ⚠️ and re-enables. No crash.
- A draft never overwrites the saved note on disk — it only populates the textarea
  until the user explicitly saves.

## Testing (pytest, network mocked — CLAUDE.md conventions)

`tests/unit/test_site_note_draft.py`:

- **`build_messages` (pure):** returns `[system, user]`; system demands the three
  Markdown sections (要点 / 为什么值得记 / 待探索) and plain Markdown; user contains
  the item's title/summary/keywords; when `existing_note` is non-empty the user
  message includes it and the system asks not to repeat it.
- **Route `POST /notes/{id}/draft`** (TestClient, `llm.stream_completion`
  monkeypatched to canned delta events): for a known id, streams the deltas
  (body contains the canned text and a `done`); unknown id → 404; path-unsafe id
  (e.g. `../x`) → 404.
- **Editor template:** a detail page (or the rendered partial) contains
  「AI 起草」and the `/draft` endpoint reference.

Tests reuse the exact `client` fixture pattern from `tests/unit/test_site_item_route.py`:
`shutil.copytree(FIXTURES, tmp_path/"data")` + `monkeypatch.setenv("AISHELF_DATA_DIR", …)`
+ `TestClient(app)`, with `from aishelf.site import app as app_module` to
`monkeypatch.setattr(app_module.llm, "stream_completion", …)`. Known id
`youtube-aaa`; unknown `nope-zzz` → 404; unsafe `a..b` → 404 (matching that file's
cases). `FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"`.

## Out of scope (YAGNI)

- No auto-save of drafts; no draft history/versioning.
- No new config, no new dependency, no DB/schema change, no sync-time work.
- No draft for the persona/graph pages — this is the per-item note editor only.
- No "regenerate/variants" UI — one button, re-clickable.

## File touch list

- **new** `src/aishelf/site/notedraft.py`
- **new** `tests/unit/test_site_note_draft.py`
- **edit** `src/aishelf/site/app.py` (1 route + import `notedraft`)
- **edit** `src/aishelf/site/templates/_note_editor.html` (button + draft JS)
- **edit** `src/aishelf/site/static/style.css` — only if a small tweak is needed
  (prefer reusing existing button classes; likely no change)
- **edit** `CLAUDE.md` (document `notedraft.py` + the route)

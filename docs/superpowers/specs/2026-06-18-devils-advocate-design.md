# 抬杠 / 反方视角 (devil's-advocate) — Design

**Date:** 2026-06-18
**Status:** Approved (autonomous-iteration; author = approver, rationale logged inline)

## Why

Every Atlas feature so far is **supportive**: it summarizes (钩子), synthesizes
(碰撞, 镜子), drafts (笔记草稿), and sequences (进阶路线). Nothing ever **pushes
back**. A personal library that only agrees with you is an echo chamber — you save
something, nod, move on. The most valuable second voice on a saved idea is the one
that argues *against* it.

「抬杠」adds the first **adversarial** feature: a 「🔥 唱个反调」button on each item's
detail page streams a sharp 中文 critique — the content's likely 软肋, the strongest
opposing case (steel-manned), and what evidence would change the conclusion. If you
have written a note on the item, it pushes back on **your** take too, not just the
content's.

Fits the taste (简洁 + 实用 + 好玩，拒绝花里胡哨; distill rather than decorate;
reuse the LLM client). **好玩** = an AI that disagrees with your saved content and
your own notes — high content-surprise, no visual gimmickry. **实用** = stress-tests
what you consumed; complements 笔记草稿 (draft captures, 反方 interrogates). Same
on-demand, no-persistence, no-new-config shape as `/collide` / `/mirror`. Clearly
distinct from 笔记草稿's neutral 待探索 (a study aid that goes *into* your note);
this is an ephemeral adversarial stance, shown not saved, that engages your note.

## What it is

- A 「🔥 唱个反调」button on each item's detail page (a shared `_critique.html`
  partial included in `video_detail.html` and `blog_detail.html`, between the
  keywords and the note editor).
- `POST /critique/{id}` loads the item (per-request file model) + its existing note
  and **streams** the critique via `llm.stream_completion`. Ungated (cheap, like
  `/ask`/`/collide`/`/mirror`/`/notes/{id}/draft`).
- On-demand, **no persistence, no caching**. The critique is shown in a panel; never
  saved.

### The critique (LLM output)

Plain text, no Markdown, honest that it reasons from summary-level info. Exactly:

```
【最薄弱的地方】 这条内容的论点/前提里最可能站不住或被忽略的一点。1-2 句。
【反方会怎么说】 把最强的反对立场讲出来（steel-man，不是稻草人）。1-2 句。
【什么能说服你改主意】 一个具体的证据/观察，出现了就该改判。1 句。
```

When the user has a note, the system prompt also tells the model to challenge the
**user's recorded take** where it can — making the pushback personal.

## Architecture — mirrors `notedraft.py` / `collide.py` / `mirror.py`

New leaf module `src/aishelf/site/critique.py` — pure `build_messages` only (no DB,
no LLM). The route does the item lookup + streaming, reusing existing app helpers
(identical shape to the `/notes/{id}/draft` route).

```python
build_messages(item: dict, note: str = "") -> list[dict]   # pure
```

- `item` is the dict shape from `app._item_dict(it)` (`title`, `summary`,
  `keywords`, `author`, `type`).
- `note`: the user's existing note (empty string when none). When non-empty, the
  prompt additionally challenges the user's take and the note text is included in
  the user message.

System prompt: a 中文 "好抬杠但讲道理" critic; output the three bracketed sections
above; steel-man the opposition (no strawman); honest that it reasons from a
summary, not full text; plain text, no Markdown; no preamble/closing. User message:
the item's title/type/author/summary/keywords, plus the user's note when present.

### Route wiring (`app.py`)

```python
@app.post("/critique/{item_id}")
def critique_route(item_id: str):
    # Ungated: critique is cheap (like /ask, /collide, /notes/{id}/draft), not the Hermes path.
    try:
        items.safe_id(item_id)
    except ValueError:
        raise HTTPException(status_code=404)
    it = next((x for x in _items() if x.id == item_id), None)
    if it is None:
        raise HTTPException(status_code=404)
    note = _note_for(it)

    def _gen():
        yield from llm.stream_completion(critique.build_messages(_item_dict(it), note))

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

Reuses `items.safe_id`, `_items()`, `_note_for`, `_item_dict`, `llm`,
`StreamingResponse` — the exact set `/notes/{id}/draft` uses. `critique` added to the
`aishelf.site` import block. `llm.stream_completion` already yields `{"delta"}` +
final `{"done": true}` and converts an unconfigured/unreachable model into an
`{"error"}` event — graceful degradation with no extra code.

### Frontend (`_critique.html` partial)

A shared partial (like `_note_editor.html`) included in both detail templates,
passed the same `item` in context (so `{{ item.id }}` works). Contents:

- a `<section class="critique">` with an `<h2>抬杠</h2>` + 「🔥 唱个反调」button
  (`id="critique-btn"`) and a result panel (`id="critique-result"`).
- an IIFE `<script>` (self-contained — must not collide with `_note_editor.html`'s
  IIFE; all vars local): on click, disable the button, show 「正在抬杠…」, POST
  `/critique/{id}`, read the SSE stream with the same delta-reader loop as
  `mirror.html`, accumulate, and set `result.textContent = acc` (inert — no
  innerHTML from stream). On `{"error"}` show ⚠️; re-enable the button in a
  `finally`. Re-clickable (re-streams a fresh critique).

Placed after `{% include "_keywords.html" %}` and before `{% include "_note_editor.html" %}`
in both `video_detail.html` and `blog_detail.html` — read → get challenged → take notes.

### Styling

Add a small `.critique` block to `static/style.css` reusing the streamed-result
panel look from `.mirror`/`.learn-result` (a distinct warm accent to signal the
adversarial tone). Reuse the existing `.btn`/`.btn-link` button classes. No new assets.

## Error handling

- Unknown/unsafe id → 404 (`safe_id` guard + `_items()` lookup), like
  `/notes/{id}/draft` and `/api/item/{id}`.
- Chat model unconfigured/unreachable → `llm.stream_completion` `{"error"}` event +
  `{"done": true}`; the panel shows ⚠️ and re-enables. No crash.
- Critique is never persisted; it lives only in the panel until the next click /
  page reload.
- Stream text set via `textContent`; the partial's JS uses only local vars (no
  global collision with the note-editor IIFE).

## Testing (pytest, network mocked — CLAUDE.md conventions)

`tests/unit/test_site_critique.py`:

- **`build_messages` (pure):** returns `[system, user]`; system demands the three
  bracketed sections (最薄弱的地方 / 反方会怎么说 / 什么能说服你改主意), steel-man
  (no strawman), plain text (no Markdown); user contains the item title/summary/
  keywords; when `note` is non-empty the user message includes it and the system
  prompt references challenging the user's take.
- **Route `POST /critique/{id}`** — reuse the `client` fixture pattern from
  `tests/unit/test_site_note_draft.py` (`shutil.copytree(FIXTURES, tmp/"data")` +
  `monkeypatch.setenv("AISHELF_DATA_DIR", …)` + `monkeypatch.setattr(app_module.llm,
  "stream_completion", …)`): known id `youtube-aaa` streams the canned deltas;
  unknown `nope-zzz` → 404; unsafe `a..b` → 404.
- **Detail templates:** `GET /videos/youtube-aaa` and a blog detail page each
  contain 「唱个反调」and the `/critique/` endpoint reference (partial wired into both).

## Out of scope (YAGNI)

- No persistence/history of critiques; no rebuttal threading.
- No critique on list/graph/mirror pages — detail page only.
- No new config, dependency, DB/schema change, or sync-time work.
- No "regenerate variants" UI — one button, re-clickable.

## File touch list

- **new** `src/aishelf/site/critique.py`
- **new** `src/aishelf/site/templates/_critique.html`
- **new** `tests/unit/test_site_critique.py`
- **edit** `src/aishelf/site/app.py` (1 route + import `critique`)
- **edit** `src/aishelf/site/templates/video_detail.html` (include partial)
- **edit** `src/aishelf/site/templates/blog_detail.html` (include partial)
- **edit** `src/aishelf/site/static/style.css` (small `.critique` block)
- **edit** `CLAUDE.md` (document `critique.py` + the route)

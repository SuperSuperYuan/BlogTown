# 「灵感碰撞」(Idea Collision) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/collide` page that serves a surprising pair of library items and an LLM-streamed three-part synthesis of how they relate; random-first with "再来一对" reshuffle and a per-card lock.

**Architecture:** A pure pair-selection module (`collide.py`) mirrors how `graph.py` splits an impure loader (`load_pair_space`) from pure logic (`pick_pair`/`random_pair`/`build_messages`). One streaming endpoint `POST /collide/chat` picks the pair, emits it as a `pair` SSE event, then `yield from llm.stream_completion(...)` — mirroring `/ask/chat` (which emits `sources` then streams). The page reuses `/ask`'s fetch+reader SSE client pattern; output is plain text (no client markdown lib).

**Tech Stack:** Python, FastAPI + Jinja2, numpy (cosine), SQLite, OpenAI-compatible chat client, pytest.

**Spec:** `docs/superpowers/specs/2026-06-17-idea-collision-design.md`

---

## File Structure

- `src/aishelf/site/collide.py` (new) — `pick_pair`, `random_pair`, `load_pair_space`, `build_messages` (+ `_cosine_matrix`). Pure selection logic + one thin DB loader.
- `src/aishelf/site/app.py` — `_CollideRequest` model, `_resolve_pair` + `_collide_ref`/`_item_dict` helpers, `GET /collide`, `POST /collide/chat`.
- `src/aishelf/site/templates/collide.html` (new) — focused page + vanilla-JS SSE client.
- `src/aishelf/site/templates/_topbar.html` — add 「碰撞」nav link.
- `src/aishelf/site/static/style.css` — collide styles.
- Tests: `tests/unit/test_collide.py` (new), `tests/unit/test_site_collide_routes.py` (new).
- `CLAUDE.md` — document the feature.

---

## Task 1: `collide.py` — pair selection (`pick_pair` + `random_pair`)

**Files:**
- Create: `src/aishelf/site/collide.py`
- Test: `tests/unit/test_collide.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_collide.py`:

```python
import math
import random

import numpy as np

from aishelf.site import collide


def _vec(deg):
    r = math.radians(deg)
    return [math.cos(r), math.sin(r)]


def test_pick_pair_only_in_band():
    # cos(0,66)=0.407 (in [0.30,0.50)); cos(0,8)=0.990 (>=hi, excluded);
    # cos(66,8)=cos58=0.530 (>=hi, excluded) -> only (a,b) qualifies.
    ids = ["a", "b", "c"]
    matrix = np.array([_vec(0), _vec(66), _vec(8)], dtype=np.float32)
    meta = {"a": {"type": "video", "author": "X"},
            "b": {"type": "blog", "author": "Y"},
            "c": {"type": "video", "author": "Z"}}
    assert collide.pick_pair(ids, matrix, meta, rng=random.Random(0)) == ("a", "b")


def test_pick_pair_prefers_cross_type_author():
    # (a,b) in-band same type+author -> score 0; (a,c) in-band cross -> score 2.
    ids = ["a", "b", "c"]
    matrix = np.array([_vec(0), _vec(66), _vec(67)], dtype=np.float32)
    meta = {"a": {"type": "video", "author": "X"},
            "b": {"type": "video", "author": "X"},
            "c": {"type": "blog", "author": "Y"}}
    assert collide.pick_pair(ids, matrix, meta, rng=random.Random(0)) == ("a", "c")


def test_pick_pair_lock_id_restricts_and_orders():
    # lock 'b': only (a,b) is in-band and contains b -> returned with b first.
    ids = ["a", "b", "c"]
    matrix = np.array([_vec(0), _vec(66), _vec(67)], dtype=np.float32)
    meta = {"a": {"type": "video", "author": "X"},
            "b": {"type": "blog", "author": "Y"},
            "c": {"type": "blog", "author": "Z"}}
    assert collide.pick_pair(ids, matrix, meta, lock_id="b", rng=random.Random(0)) == ("b", "a")


def test_pick_pair_none_when_no_band():
    ids = ["a", "b"]
    matrix = np.array([_vec(0), _vec(2)], dtype=np.float32)  # cos2=0.999 too high
    meta = {"a": {"type": "video", "author": "X"}, "b": {"type": "blog", "author": "Y"}}
    assert collide.pick_pair(ids, matrix, meta, rng=random.Random(0)) is None


def test_pick_pair_none_when_too_few():
    matrix = np.array([_vec(0)], dtype=np.float32)
    assert collide.pick_pair(["a"], matrix, {"a": {}}, rng=random.Random(0)) is None


def test_random_pair_two_distinct():
    p = collide.random_pair(["a", "b", "c"], rng=random.Random(0))
    assert p[0] != p[1] and set(p) <= {"a", "b", "c"}


def test_random_pair_honors_lock():
    assert collide.random_pair(["a", "b", "c"], lock_id="a", rng=random.Random(0))[0] == "a"


def test_random_pair_none_when_too_few():
    assert collide.random_pair(["a"], rng=random.Random(0)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_collide.py -v`
Expected: FAIL with `ImportError` / `AttributeError` (no `aishelf.site.collide` / no `pick_pair`).

- [ ] **Step 3: Implement the module skeleton + the two functions**

Create `src/aishelf/site/collide.py`:

```python
"""Idea-collision pair selection + prompt building (mostly pure).

Mirrors graph.py's split: pure selection logic (pick_pair / random_pair /
build_messages) plus one thin DB loader (load_pair_space). Picks a "surprising"
pair — embedding cosine in a mid band [0.30, GRAPH_SIM_FLOOR), preferring
cross-type and cross-author — for the LLM to synthesize. Reuses ATLAS_CHAT_* via
the site llm client and ATLAS_EMBED_* via stored embeddings; no new config.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from aishelf.db import graph, schema, vector

BAND_LO = 0.30
BAND_HI = graph.GRAPH_SIM_FLOOR  # 0.50 — at/above this the graph already draws an edge


def _cosine_matrix(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normed = matrix / (norms + 1e-12)
    return normed @ normed.T


def pick_pair(ids, matrix, meta, *, lock_id=None, rng, lo=BAND_LO, hi=BAND_HI):
    """A surprising (id_a, id_b) pair: cosine in [lo, hi), preferring cross-type
    and cross-author, chosen at random (via rng) from the best-scoring tier.
    With lock_id, restrict to pairs containing it and return it first. None when
    there are fewer than 2 items or no in-band candidates (caller falls back)."""
    n = len(ids)
    if n < 2:
        return None
    sims = _cosine_matrix(np.asarray(matrix, dtype=np.float32))
    cands = []  # (score, a, b)
    for i in range(n):
        for j in range(i + 1, n):
            s = float(sims[i, j])
            if not (lo <= s < hi):
                continue
            a, b = ids[i], ids[j]
            if lock_id is not None and lock_id not in (a, b):
                continue
            ma, mb = meta.get(a, {}), meta.get(b, {})
            score = int(ma.get("type") != mb.get("type")) + int(ma.get("author") != mb.get("author"))
            cands.append((score, a, b))
    if not cands:
        return None
    best = max(c[0] for c in cands)
    top = sorted((c for c in cands if c[0] == best), key=lambda c: (c[1], c[2]))
    _, a, b = rng.choice(top)
    if lock_id is not None and b == lock_id:
        a, b = b, a
    return (a, b)


def random_pair(item_ids, *, lock_id=None, rng):
    """Fallback: two distinct ids at random (honoring lock_id). None when <2."""
    ids = list(item_ids)
    if len(ids) < 2:
        return None
    if lock_id is not None and lock_id in ids:
        others = [i for i in ids if i != lock_id]
        return (lock_id, rng.choice(others))
    return tuple(rng.sample(ids, 2))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_collide.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/collide.py tests/unit/test_collide.py
git commit -m "feat(collide): pure pick_pair + random_pair selection"
```

---

## Task 2: `collide.py` — `load_pair_space` + `build_messages`

**Files:**
- Modify: `src/aishelf/site/collide.py`
- Test: `tests/unit/test_collide.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_collide.py`:

```python
import json

from aishelf import embed, alias as _alias
from aishelf.db.sync import sync


def _write_video(data_dir, vid, summary="普通摘要"):
    (data_dir / "videos").mkdir(parents=True, exist_ok=True)
    rec = {"id": vid, "type": "video", "title": f"标题{vid}", "author": "作者甲",
           "platform": "youtube", "source_url": f"https://x/{vid}",
           "published_at": "2024-01-01", "summary": summary, "keywords": [],
           "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}
    (data_dir / "videos" / f"{vid}.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def test_load_pair_space_empty_when_no_embeddings(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(_alias, "is_configured", lambda: False)
    sync(data, db)
    ids, matrix, meta = collide.load_pair_space(db)
    assert ids == [] and meta == {} and matrix.shape[0] == 0


def test_load_pair_space_groups_embedded(tmp_path, monkeypatch):
    data, db = tmp_path / "data", tmp_path / "atlas.db"
    _write_video(data, "v1")
    _write_video(data, "v2")
    monkeypatch.setattr(embed, "model_name", lambda: "m")
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(_alias, "is_configured", lambda: False)
    sync(data, db)
    ids, matrix, meta = collide.load_pair_space(db)
    assert set(ids) == {"v1", "v2"}
    assert matrix.shape == (2, 2)
    assert meta["v1"]["type"] == "video" and meta["v1"]["author"] == "作者甲"


def test_load_pair_space_tolerates_missing_db(tmp_path):
    ids, matrix, meta = collide.load_pair_space(tmp_path / "nope.db")
    assert ids == [] and meta == {}


def test_build_messages_structure():
    msgs = collide.build_messages(
        {"title": "标题A", "summary": "摘要A", "keywords": ["k1"], "author": "作者A", "type": "video"},
        {"title": "标题B", "summary": "摘要B", "keywords": [], "author": "作者B", "type": "blog"},
    )
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    for label in ["【共同的暗线】", "【关键张力】", "【碰撞出的新点子】"]:
        assert label in msgs[0]["content"]
    assert "Markdown" in msgs[0]["content"]
    assert "标题A" in msgs[1]["content"] and "标题B" in msgs[1]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_collide.py -k "load_pair_space or build_messages" -v`
Expected: FAIL with `AttributeError: module 'aishelf.site.collide' has no attribute 'load_pair_space'`.

- [ ] **Step 3: Implement both functions**

Append to `src/aishelf/site/collide.py`:

```python
def load_pair_space(db_path):
    """(ids, matrix, meta) for the largest same-dimension embedding group.

    meta[id] = {"type", "author"}. Returns empties when there are no embeddings
    or the DB is missing/old (so the caller can fall back to a random pair).
    """
    empty = ([], np.empty((0, 0), dtype=np.float32), {})
    try:
        con = schema.connect(db_path)
        try:
            schema.init_db(con)
            rows = con.execute(
                "SELECT id, embedding, embedding_dim, type, author FROM items "
                "WHERE embedding IS NOT NULL"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return empty
    by_dim: dict[int, list] = {}
    for r in rows:
        by_dim.setdefault(r["embedding_dim"], []).append(r)
    if not by_dim:
        return empty
    dim = max(by_dim, key=lambda d: len(by_dim[d]))
    group = by_dim[dim]
    ids = [r["id"] for r in group]
    matrix = np.stack([vector.unpack(r["embedding"]) for r in group])
    meta = {r["id"]: {"type": r["type"], "author": r["author"]} for r in group}
    return ids, matrix, meta


def _fmt_item(x) -> str:
    kw = "、".join(x.get("keywords") or [])
    lines = [f"标题：{x['title']}", f"作者：{x.get('author', '')}", f"摘要：{x.get('summary', '')}"]
    if kw:
        lines.append(f"关键词：{kw}")
    return "\n".join(lines)


def build_messages(a, b) -> list[dict]:
    """System + user messages asking for exactly three plain-text sections.
    `a`/`b` are dicts with title/summary/keywords/author/type."""
    system = (
        "你是一个善于发现跨领域联系的思考者。用户会给你两条 AI 领域的内容，"
        "请把它们放在一起碰撞，输出恰好三段，每段以方括号小标题开头，每段 1-2 句，"
        "具体、有锋芒、不要空话套话：\n"
        "【共同的暗线】它们没明说但共享的线索。\n"
        "【关键张力】它们相互拉扯或分歧之处。\n"
        "【碰撞出的新点子】把两者结合后迸发的一个新想法。\n"
        "只输出这三段纯文本，不要使用 Markdown 语法（不要 # 或 * 等），"
        "不要额外的开场白或总结。"
    )
    user = (
        f"内容 A（{a.get('type', '')}）：\n{_fmt_item(a)}\n\n"
        f"内容 B（{b.get('type', '')}）：\n{_fmt_item(b)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

- [ ] **Step 4: Run the full collide test file**

Run: `pytest tests/unit/test_collide.py -v`
Expected: PASS (all of Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/collide.py tests/unit/test_collide.py
git commit -m "feat(collide): load_pair_space loader + build_messages prompt"
```

---

## Task 3: `POST /collide/chat` route + resolution helpers

**Files:**
- Modify: `src/aishelf/site/app.py`
- Test: `tests/unit/test_site_collide_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_site_collide_routes.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

from aishelf.site import hermes, llm


def _write(data_dir, sub, item_id, title):
    rec = {
        "id": item_id, "type": "video" if sub == "videos" else "blog",
        "title": title, "author": "作者甲",
        "platform": "youtube" if sub == "videos" else "blog",
        "source_url": f"https://x/{item_id}", "published_at": "2024-01-01",
        "summary": "摘要", "keywords": [], "collected_at": "2024-01-02T00:00:00",
    }
    if sub == "videos":
        rec["thumbnail_url"] = "https://img/x.jpg"
    d = data_dir / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{item_id}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _fake_stream(messages):
    yield hermes.sse({"delta": "碰撞结果"})
    yield hermes.sse({"done": True})


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    _write(tmp_path, "videos", "v1", "视频标题")
    _write(tmp_path, "blogs", "b1", "博客标题")
    from aishelf import embed, alias
    monkeypatch.setattr(embed, "model_name", lambda: None)       # no embeddings -> random_pair path
    monkeypatch.setattr(alias, "is_configured", lambda: False)
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")
    monkeypatch.setattr(llm, "stream_completion", _fake_stream)  # no real LLM call
    from aishelf.site.app import app
    return TestClient(app)


def test_collide_chat_emits_pair_then_delta(client):
    r = client.post("/collide/chat", json={})
    assert r.status_code == 200
    evs = _events(r.text)
    assert "pair" in evs[0]
    assert set(evs[0]["pair"]) == {"a", "b"}
    assert {evs[0]["pair"]["a"]["id"], evs[0]["pair"]["b"]["id"]} == {"v1", "b1"}
    assert any(e.get("delta") == "碰撞结果" for e in evs)


def test_collide_chat_honors_explicit_ids(client):
    r = client.post("/collide/chat", json={"a_id": "v1", "b_id": "b1"})
    evs = _events(r.text)
    assert {evs[0]["pair"]["a"]["id"], evs[0]["pair"]["b"]["id"]} == {"v1", "b1"}


def test_collide_chat_honors_lock_id(client):
    r = client.post("/collide/chat", json={"lock_id": "v1"})
    evs = _events(r.text)
    assert "v1" in {evs[0]["pair"]["a"]["id"], evs[0]["pair"]["b"]["id"]}


def test_collide_chat_empty_library(monkeypatch, tmp_path):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AISHELF_DB_PATH", str(tmp_path / "atlas.db"))
    from aishelf import embed, alias
    monkeypatch.setattr(embed, "model_name", lambda: None)
    monkeypatch.setattr(alias, "is_configured", lambda: False)
    from aishelf.db.sync import sync
    sync(tmp_path, tmp_path / "atlas.db")   # no items
    from aishelf.site.app import app
    client = TestClient(app)
    evs = _events(client.post("/collide/chat", json={}).text)
    assert any("先去采集" in (e.get("error") or "") for e in evs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_site_collide_routes.py -v`
Expected: FAIL with 404 (route not defined) — assertions on `evs[0]` raise / status != 200.

- [ ] **Step 3: Add imports, request model, helpers, and the route**

In `src/aishelf/site/app.py`:

(a) Add `import random` near the other stdlib imports (after `import os`).

(b) Add `collide` to the `from aishelf.site import (...)` tuple (keep alphabetical: it goes between `ask` and `collect`).

(c) After the `_hooks_for` helper, add the resolution helpers:

```python
def _collide_ref(it) -> dict:
    return {"id": it.id, "type": it.type, "title": it.title, "author": it.author}


def _item_dict(it) -> dict:
    return {"title": it.title, "summary": it.summary, "keywords": it.keywords,
            "author": it.author, "type": it.type}


def _resolve_pair(items, space, *, a_id, b_id, lock_id, rng):
    """Resolve a (item_a, item_b) pair from explicit ids, else a surprising pick
    (with random fallback). Returns None when no pair can be formed."""
    by_id = {it.id: it for it in items}
    if a_id and b_id:
        pair = (a_id, b_id)
    else:
        ids, matrix, meta = space
        pair = collide.pick_pair(ids, matrix, meta, lock_id=lock_id, rng=rng)
        if pair is None:
            pair = collide.random_pair(list(by_id), lock_id=lock_id, rng=rng)
    if pair is None:
        return None
    a, b = by_id.get(pair[0]), by_id.get(pair[1])
    if a is None or b is None:
        return None
    return (a, b)
```

(d) Add the request model next to `_ChatRequest`:

```python
class _CollideRequest(BaseModel):
    a_id: str | None = None
    b_id: str | None = None
    lock_id: str | None = None
```

(e) Add the route after the `/ask/chat` route:

```python
@app.post("/collide/chat")
def collide_chat(req: _CollideRequest):
    # Ungated: synthesis is cheap (like /ask), not the costly Hermes path.
    data_dir = get_data_dir()
    items = _items()
    space = collide.load_pair_space(default_db_path(data_dir))
    pair = _resolve_pair(items, space, a_id=req.a_id, b_id=req.b_id,
                         lock_id=req.lock_id, rng=random.Random())

    def _gen():
        if pair is None:
            yield hermes.sse({"error": "先去采集一些内容再来碰撞"})
            yield hermes.sse({"done": True})
            return
        a, b = pair
        yield hermes.sse({"pair": {"a": _collide_ref(a), "b": _collide_ref(b)}})
        yield from llm.stream_completion(collide.build_messages(_item_dict(a), _item_dict(b)))

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_site_collide_routes.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_collide_routes.py
git commit -m "feat(site): POST /collide/chat — emit pair, stream synthesis"
```

---

## Task 4: `GET /collide` page + nav + styles

**Files:**
- Modify: `src/aishelf/site/app.py` (add `GET /collide`)
- Create: `src/aishelf/site/templates/collide.html`
- Modify: `src/aishelf/site/templates/_topbar.html`, `src/aishelf/site/static/style.css`
- Test: `tests/unit/test_site_collide_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_site_collide_routes.py`:

```python
def test_collide_page_renders(client):
    r = client.get("/collide")
    assert r.status_code == 200
    assert "灵感碰撞" in r.text
    assert "/collide/chat" in r.text  # the page wires up the streaming endpoint
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_site_collide_routes.py::test_collide_page_renders -v`
Expected: FAIL (404 — `GET /collide` not defined / template missing).

- [ ] **Step 3: Add the `GET /collide` route**

In `src/aishelf/site/app.py`, immediately before the `collide_chat` route, add:

```python
@app.get("/collide", response_class=HTMLResponse)
def collide_page(request: Request):
    return templates.TemplateResponse(request, "collide.html", {})
```

- [ ] **Step 4: Create the page template**

Create `src/aishelf/site/templates/collide.html`:

```html
{% extends "base.html" %}
{% block content %}
<section class="collide">
  <h2>灵感碰撞 <span class="hint">两条内容，碰出一个新想法</span></h2>
  <div class="collide-pair" id="pair"></div>
  <div class="collide-controls"><button id="again" type="button">再来一对 ↻</button></div>
  <div class="collide-result" id="result"></div>
</section>
<script>
(function () {
  const pairEl = document.getElementById('pair');
  const resultEl = document.getElementById('result');
  const againBtn = document.getElementById('again');
  let lockId = null, busy = false;

  function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

  function cardHtml(item) {
    const href = (item.type === 'video' ? '/videos/' : '/blogs/') + encodeURIComponent(item.id);
    const locked = lockId === item.id;
    return '<div class="cc ' + (locked ? 'locked' : '') + '" data-id="' + escapeHtml(item.id) + '">'
      + '<button class="lock" type="button" title="锁定后只换另一边">' + (locked ? '🔒' : '🔓') + '</button>'
      + '<span class="cc-type">' + (item.type === 'video' ? '视频' : '博客') + '</span>'
      + '<a class="cc-title" href="' + href + '">' + escapeHtml(item.title) + '</a>'
      + '<div class="cc-author">' + escapeHtml(item.author || '') + '</div></div>';
  }

  function renderPair(p) {
    pairEl.innerHTML = cardHtml(p.a) + '<div class="collide-x">✦</div>' + cardHtml(p.b);
    pairEl.querySelectorAll('.cc').forEach(card => {
      card.querySelector('.lock').addEventListener('click', () => {
        const id = card.getAttribute('data-id');
        lockId = (lockId === id) ? null : id;
        pairEl.querySelectorAll('.cc').forEach(c => {
          const on = c.getAttribute('data-id') === lockId;
          c.classList.toggle('locked', on);
          c.querySelector('.lock').textContent = on ? '🔒' : '🔓';
        });
      });
    });
  }

  async function run() {
    if (busy) return;
    busy = true; againBtn.disabled = true; resultEl.textContent = '正在碰撞…';
    let resp;
    try {
      resp = await fetch('/collide/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(lockId ? { lock_id: lockId } : {}),
      });
    } catch (e) { resultEl.textContent = '⚠️ 无法连接服务'; busy = false; againBtn.disabled = false; return; }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '', acc = '', streaming = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let p; try { p = JSON.parse(line.slice(6)); } catch (e) { continue; }
        if (p.pair) { renderPair(p.pair); }
        else if (p.delta) { if (!streaming) { streaming = true; acc = ''; } acc += p.delta; resultEl.textContent = acc; }
        else if (p.error) { resultEl.textContent = '⚠️ ' + p.error; }
      }
    }
    busy = false; againBtn.disabled = false;
  }

  againBtn.addEventListener('click', run);
  run();
})();
</script>
{% endblock %}
```

- [ ] **Step 5: Add the nav link**

In `src/aishelf/site/templates/_topbar.html`, change the `<nav>` line to add 「碰撞」after 图谱:

```html
  <nav><a href="/videos">视频</a><a href="/blogs">博客</a><a href="/write">写博客</a><a href="/ask">问答</a><a href="/graph">图谱</a><a href="/collide">碰撞</a><a href="/collect">Hermes</a></nav>
```

- [ ] **Step 6: Add styles**

Append to `src/aishelf/site/static/style.css`:

```css
.collide .hint { font-size: 13px; color: #7b8794; font-weight: normal; }
.collide-pair { display: flex; align-items: stretch; gap: 12px; margin: 12px 0; }
.collide-pair .cc { flex: 1; position: relative; background: #fff; border: 1px solid #e7e9ef; border-radius: 12px; padding: 14px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.collide-pair .cc.locked { border-color: #0a84ff; box-shadow: 0 0 0 2px rgba(10,132,255,.18); }
.collide-pair .cc-type { font-size: 12px; color: #7b8794; }
.collide-pair .cc-title { display: block; margin: 4px 0; font-weight: 600; color: #1f2933; text-decoration: none; }
.collide-pair .cc-title:hover { color: #0a84ff; }
.collide-pair .cc-author { font-size: 12px; color: #7b8794; }
.collide-pair .lock { position: absolute; top: 8px; right: 8px; border: none; background: none; cursor: pointer; font-size: 15px; line-height: 1; }
.collide-x { align-self: center; color: #0a84ff; font-size: 22px; }
.collide-controls { margin: 6px 0 14px; }
.collide-controls button { background: #0a84ff; color: #fff; border: none; border-radius: 8px; padding: 7px 14px; cursor: pointer; font-size: 14px; }
.collide-controls button:disabled { opacity: .5; cursor: default; }
.collide-result { white-space: pre-wrap; line-height: 1.7; color: #1f2933; background: #fafbfc; border: 1px solid #e7e9ef; border-radius: 12px; padding: 16px; min-height: 60px; }
```

- [ ] **Step 7: Run the route tests + full suite**

Run: `pytest tests/unit/test_site_collide_routes.py -v` then `pytest -q`
Expected: PASS (the page test + all 4 prior route tests + whole suite green).

- [ ] **Step 8: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/collide.html src/aishelf/site/templates/_topbar.html src/aishelf/site/static/style.css tests/unit/test_site_collide_routes.py
git commit -m "feat(site): /collide page, 碰撞 nav link, styles"
```

---

## Task 5: Documentation + full-suite verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

In the `aishelf/site/` architecture bullet, add `collide.py` to the module list with a terse description: *(idea-collision: pure `pick_pair`/`random_pair` — mid-band cosine [0.30, 0.50) preferring cross-type/author — plus `load_pair_space` loader and `build_messages`; `GET /collide` + `POST /collide/chat` emit the chosen pair then stream a three-part synthesis via `llm.stream_completion`; on-demand, no persistence, reuses `ATLAS_CHAT_*`/`ATLAS_EMBED_*`)*. Match the existing terse style; weave it in rather than adding a section.

- [ ] **Step 2: Run the full test suite**

Run: `pytest -q`
Expected: PASS (network tests skipped by default).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document 灵感碰撞 (/collide, collide.py)"
```

---

## Self-Review

- **Spec coverage:** interaction random-first + reshuffle + lock (Task 4 page JS) ✓; mid-band [0.30,0.50) cosine + cross-type/author preference (`pick_pair`, Task 1) ✓; three plain-text sections (`build_messages`, Task 2) ✓; single endpoint emits `pair` then streams (Task 3) ✓; degradation to random pair / empty-state / missing-DB tolerance (`random_pair`, `load_pair_space`, `_resolve_pair`, Tasks 1–3) ✓; nav link (Task 4) ✓; no persistence / no new config / no client markdown lib (design honored — none added) ✓; docs (Task 5) ✓. Non-goals (no detail-page entry UI, no 3+ collisions, no home/graph surfacing) — no task adds them. Note: `a_id/b_id` are accepted by the route + tested but no UI links to them, exactly as the spec states.
- **Placeholder scan:** none — every code step has full code; every run step has a command + expected outcome.
- **Type consistency:** `pick_pair(ids, matrix, meta, *, lock_id, rng, lo, hi) -> tuple|None`, `random_pair(item_ids, *, lock_id, rng) -> tuple|None`, `load_pair_space(db_path) -> (ids, matrix, meta)`, `build_messages(a, b) -> list[dict]`, `_resolve_pair(...) -> (item, item)|None`, `_collide_ref`/`_item_dict`, `_CollideRequest{a_id,b_id,lock_id}`, SSE keys `pair`/`delta`/`error`/`done`, `BAND_LO`/`BAND_HI` — consistent across tasks and tests. `build_messages` consumes dicts; the route builds them via `_item_dict` (consistent).

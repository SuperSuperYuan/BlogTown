# 进阶路线 / 学习路径 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 「进阶路线」page that turns a chosen theme galaxy into an ordered, streamed 中文 reading curriculum with clickable item links.

**Architecture:** A new leaf module `aishelf/site/learn.py` (pure `build_messages` + one tolerant DB loader `load_galaxies`, mirrors `collide.py`/`mirror.py`). Two routes: `GET /learn` server-renders galaxy pills + embeds each galaxy's `{id,title,type}` items as JSON; `POST /learn/route` streams the curriculum via `llm.stream_completion`. No persistence, no new config/deps.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite (derived DB), pytest + FastAPI TestClient.

---

### Task 1: `learn.py` — dataclasses + pure `build_messages`

**Files:**
- Create: `src/aishelf/site/learn.py`
- Test: `tests/unit/test_site_learn.py`

- [ ] **Step 1: Write the failing test** (create `tests/unit/test_site_learn.py`):

```python
from aishelf.site import learn


_ITEMS = [
    {"id": "v1", "title": "推理模型入门", "summary": "什么是推理模型。", "type": "video"},
    {"id": "v2", "title": "测试时计算", "summary": "推理阶段扩展算力。", "type": "video"},
    {"id": "b1", "title": "思维链评测", "summary": "如何评测推理。", "type": "blog"},
]


def test_build_messages_shape_and_content():
    msgs = learn.build_messages("推理模型", _ITEMS)
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    # asks for an ordered progression, step starts with the exact title, plain text
    assert "顺序" in system or "进阶" in system
    assert "标题" in system          # told to start each step with the item's title
    assert "Markdown" in system or "markdown" in system
    # user grounds the model in the galaxy + its items
    assert "推理模型" in user
    assert "推理模型入门" in user and "思维链评测" in user
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_site_learn.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aishelf.site.learn'`.

- [ ] **Step 3: Create `src/aishelf/site/learn.py`:**

```python
"""Learning-path (进阶路线) loader + prompt builder, mirroring collide.py / mirror.py.

Pure `build_messages` (sequences a theme galaxy's items into an ordered 中文
curriculum) + one tolerant DB loader `load_galaxies` (reads the clusters/items
derived tables). The route does the streaming; this module only reads + phrases.
Reuses ATLAS_CHAT_* via the site llm client; no new config, no persistence.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from aishelf.db import schema


@dataclass
class Item:
    id: str
    title: str
    summary: str
    type: str       # "video" | "blog"


@dataclass
class Galaxy:
    id: int
    name: str       # cluster name; "" when unnamed
    color: str      # clusters.color
    size: int
    items: list = field(default_factory=list)   # list[Item]


def _fmt_item(i: int, it: dict) -> str:
    summary = (it.get("summary") or "")[:80]
    return f"{i}. {it.get('title', '')}（{it.get('type', '')}）— {summary}"


def build_messages(galaxy_name: str, items: list[dict]) -> list[dict]:
    """System + user messages asking for an ordered learning path over a galaxy's
    items. `items` are dicts with id/title/summary/type. Pure — no DB, no LLM."""
    system = (
        "你是一个课程设计者。用户会给你某个主题星系里收藏的若干内容（标题+摘要）。"
        "请把它们排成一条由浅入深的学习路线：入门 → 进阶 → 纵深。先用一句话概述这条线"
        "整体怎么走，然后逐条列出顺序，每条另起一行：以该内容的【完整标题原文】开头，"
        "再接“ — ”和不超过一句话的理由（为什么排在这一步）。只能用我给你的这些内容，"
        "不要杜撰别的；如果只有一条，就直说这条目前是孤本。"
        "输出纯文本，不要使用 Markdown 语法（不要 # 或 * 等），不要额外开场白或总结。"
    )
    listing = "\n".join(_fmt_item(i + 1, it) for i, it in enumerate(items))
    user = f"主题星系：{galaxy_name}\n这个星系里的内容：\n{listing}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

Note the test asserts `"顺序" in system or "进阶" in system` (both present), `"标题"`
in system (present: "完整标题原文"), and `"Markdown"` (present). All hold.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_site_learn.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/learn.py tests/unit/test_site_learn.py
git commit -m "feat(site): learn.build_messages（进阶路线提示）"
```

---

### Task 2: `learn.py` — `load_galaxies` loader

**Files:**
- Modify: `src/aishelf/site/learn.py`
- Test: `tests/unit/test_site_learn.py`

The `items` table has many NOT NULL columns; the helper below inserts full rows.

- [ ] **Step 1: Write the failing tests** — APPEND to `tests/unit/test_site_learn.py`:

```python
from aishelf.db import schema as db_schema

_ITEM_COLS = ["id", "type", "title", "author", "platform", "source_url",
              "published_at", "collected_at", "summary", "keywords",
              "content_hash", "synced_at", "cluster"]


def _insert_item(con, *, id, title="t", summary="s", type="video", cluster=None):
    vals = {"id": id, "type": type, "title": title, "author": "A", "platform": "p",
            "source_url": "https://x", "published_at": "2026-01-01T00:00:00",
            "collected_at": "2026-01-01T00:00:00", "summary": summary,
            "keywords": "[]", "content_hash": "h", "synced_at": "2026-01-01T00:00:00",
            "cluster": cluster}
    con.execute(f"INSERT INTO items ({','.join(_ITEM_COLS)}) VALUES "
                f"({','.join('?'*len(_ITEM_COLS))})", [vals[c] for c in _ITEM_COLS])


def _seed(db_path):
    con = db_schema.connect(db_path)
    db_schema.init_db(con)
    con.execute("INSERT INTO clusters (id,name,color,signature) VALUES (0,'推理','#ff9a3c','s0')")
    con.execute("INSERT INTO clusters (id,name,color,signature) VALUES (1,'多模态','#4cc2ff','s1')")
    _insert_item(con, id="v1", title="推理一", summary="基础", type="video", cluster=0)
    _insert_item(con, id="v2", title="推理二", summary="进阶", type="video", cluster=0)
    _insert_item(con, id="b1", title="推理三", summary="纵深", type="blog", cluster=0)
    _insert_item(con, id="v3", title="多模态一", summary="看图", type="video", cluster=1)
    con.commit(); con.close()


def test_load_galaxies_aggregates(tmp_path):
    db = str(tmp_path / "atlas.db")
    _seed(db)
    gs = learn.load_galaxies(db)
    assert [g.name for g in gs] == ["推理", "多模态"]      # sorted by size desc
    assert [g.size for g in gs] == [3, 1]
    assert gs[0].id == 0 and gs[0].color == "#ff9a3c"
    titles = [it.title for it in gs[0].items]
    assert set(titles) == {"推理一", "推理二", "推理三"}
    assert gs[0].items[0].summary in {"基础", "进阶", "纵深"}
    assert gs[0].items[0].type in {"video", "blog"}


def test_load_galaxies_empty_when_no_clusters(tmp_path):
    db = str(tmp_path / "atlas.db")
    con = db_schema.connect(db); db_schema.init_db(con)
    _insert_item(con, id="x", cluster=None)
    con.commit(); con.close()
    assert learn.load_galaxies(db) == []


def test_load_galaxies_empty_when_db_missing(tmp_path):
    assert learn.load_galaxies(str(tmp_path / "nope.db")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_site_learn.py -k load_galaxies -v`
Expected: FAIL — `AttributeError: module 'aishelf.site.learn' has no attribute 'load_galaxies'`.

- [ ] **Step 3: Append `load_galaxies` to `src/aishelf/site/learn.py`:**

```python
def load_galaxies(db_path) -> list:
    """All theme galaxies (each with its items), sorted by size desc. Returns []
    when there are no clustered items / the DB is missing. Tolerant of a
    missing/old DB (returns [], never raises) — like mirror.load_profile."""
    try:
        con = schema.connect(db_path)
        try:
            schema.init_db(con)
            clusters = {
                r["id"]: (r["name"] or "", r["color"] or "")
                for r in con.execute("SELECT id, name, color FROM clusters")
            }
            rows = con.execute(
                "SELECT id, type, title, summary, cluster "
                "FROM items WHERE cluster IS NOT NULL"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    by_cluster: dict[int, list] = {}
    for r in rows:
        by_cluster.setdefault(r["cluster"], []).append(r)
    galaxies = []
    for cid, members in by_cluster.items():
        name, color = clusters.get(cid, ("", ""))
        items = [Item(id=m["id"], title=m["title"], summary=m["summary"], type=m["type"])
                 for m in members]
        galaxies.append(Galaxy(id=cid, name=name, color=color, size=len(items), items=items))
    galaxies.sort(key=lambda g: (-g.size, g.name))
    return galaxies
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_learn.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/learn.py tests/unit/test_site_learn.py
git commit -m "feat(site): learn.load_galaxies（按星系读取条目）"
```

---

### Task 3: Routes `GET /learn` + `POST /learn/route`

**Files:**
- Modify: `src/aishelf/site/app.py` (import `learn`; add `_LearnRequest`; add 2 routes after the `/mirror` routes; ~line 494)
- Create: `src/aishelf/site/templates/learn.html` (minimal stub; Task 4 fleshes it out)
- Test: `tests/unit/test_site_learn.py`

- [ ] **Step 1: Write the failing route tests** — APPEND to `tests/unit/test_site_learn.py`:

```python
import aishelf.site.app as app_module
from aishelf.site.app import app
from fastapi.testclient import TestClient


def test_learn_page_renders(tmp_path, monkeypatch):
    _seed(str(tmp_path / "atlas.db"))
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    r = TestClient(app).get("/learn")
    assert r.status_code == 200
    assert "进阶路线" in r.text
    assert "推理" in r.text          # galaxy name rendered
    assert "v1" in r.text            # embedded item id (for linking)


def test_learn_route_streams_for_known_cluster(tmp_path, monkeypatch):
    _seed(str(tmp_path / "atlas.db"))
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_module.llm, "stream_completion",
                        lambda messages: iter([app_module.hermes.sse({"delta": "1. 推理一 — 起点"}),
                                               app_module.hermes.sse({"done": True})]))
    body = TestClient(app).post("/learn/route", json={"cluster_id": 0}).text
    assert '"galaxy"' in body
    assert "推理一" in body          # canned delta streamed
    assert "done" in body


def test_learn_route_error_for_unknown_cluster(tmp_path, monkeypatch):
    _seed(str(tmp_path / "atlas.db"))
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    body = TestClient(app).post("/learn/route", json={"cluster_id": 999}).text
    assert '"error"' in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_site_learn.py -k "learn_page or learn_route" -v`
Expected: FAIL — `GET /learn` 404 (no route/template).

- [ ] **Step 3a: Create the stub `src/aishelf/site/templates/learn.html`:**

```html
{% extends "base.html" %}
{% block content %}
<section class="learn">
  <h2>进阶路线</h2>
  {% for g in galaxies %}<span class="lx-pill">{{ g.name }}</span>{% endfor %}
  <script type="application/json" id="galaxies-data">{{ galaxies_json | tojson }}</script>
</section>
{% endblock %}
```

- [ ] **Step 3b: Add `learn` to the `from aishelf.site import (...)` block** in app.py
(alphabetical: insert `learn,` right after `items,`).

- [ ] **Step 3c: Add `_LearnRequest` near the other request models** (e.g. after
`_CollideRequest`/`_PathRequest`, ~line 362-369):

```python
class _LearnRequest(BaseModel):
    cluster_id: int
```

- [ ] **Step 3d: Add the two routes immediately AFTER the `/mirror/chat` route**
(which ends `return StreamingResponse(_gen(), media_type="text/event-stream")`, ~line 494):

```python
@app.get("/learn", response_class=HTMLResponse)
def learn_page(request: Request):
    galaxies = learn.load_galaxies(default_db_path(get_data_dir()))
    galaxies_json = [
        {"id": g.id, "items": [{"id": it.id, "title": it.title, "type": it.type}
                               for it in g.items]}
        for g in galaxies
    ]
    return templates.TemplateResponse(
        request, "learn.html", {"galaxies": galaxies, "galaxies_json": galaxies_json}
    )


@app.post("/learn/route")
def learn_route(req: _LearnRequest):
    # Ungated: synthesis is cheap (like /ask, /collide, /mirror), not the Hermes path.
    galaxies = learn.load_galaxies(default_db_path(get_data_dir()))
    galaxy = next((g for g in galaxies if g.id == req.cluster_id), None)

    def _gen():
        if galaxy is None or not galaxy.items:
            yield hermes.sse({"error": "这个星系还没有内容"})
            yield hermes.sse({"done": True})
            return
        yield hermes.sse({"galaxy": {"id": galaxy.id, "name": galaxy.name}})
        item_dicts = [{"id": it.id, "title": it.title, "summary": it.summary, "type": it.type}
                      for it in galaxy.items]
        yield from llm.stream_completion(learn.build_messages(galaxy.name, item_dicts))

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_learn.py -v`
Expected: PASS (all). Then `python -m pytest -q` — whole suite green.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/learn.html tests/unit/test_site_learn.py
git commit -m "feat(site): GET /learn + POST /learn/route（进阶路线流式课程）"
```

---

### Task 4: Frontend — `learn.html` + topbar link + CSS

**Files:**
- Modify: `src/aishelf/site/templates/learn.html` (replace stub)
- Modify: `src/aishelf/site/templates/_topbar.html` (nav link)
- Modify: `src/aishelf/site/static/style.css` (small `.learn` block)
- Test: `tests/unit/test_site_learn.py`

- [ ] **Step 1: Write the failing tests** — APPEND to `tests/unit/test_site_learn.py`:

```python
def test_topbar_has_learn_link(tmp_path, monkeypatch):
    _seed(str(tmp_path / "atlas.db"))
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    r = TestClient(app).get("/learn")
    assert 'href="/learn"' in r.text


def test_learn_page_has_pill_data_attr(tmp_path, monkeypatch):
    _seed(str(tmp_path / "atlas.db"))
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    r = TestClient(app).get("/learn")
    assert 'data-cid="0"' in r.text     # clickable galaxy pill carries its cluster id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_site_learn.py -k "topbar or pill_data" -v`
Expected: FAIL — stub has no `data-cid`; topbar has no `/learn` link.

- [ ] **Step 3a: Replace `src/aishelf/site/templates/learn.html` with the full page:**

```html
{% extends "base.html" %}
{% block content %}
<section class="learn">
  <h2>进阶路线 <span class="hint">挑一个主题星系，把它排成一条由浅入深的路</span></h2>
  {% if galaxies %}
  <div class="lx-pills">
    {% for g in galaxies %}
    <button type="button" class="lx-pill" data-cid="{{ g.id }}"
            style="--c: {{ g.color if g.color|length == 7 else '#888' }}">{{ g.name or '未命名' }} · {{ g.size }}</button>
    {% endfor %}
  </div>
  <div class="learn-result" id="result"></div>
  {% else %}
  <p class="hint">先采集内容并同步图谱（<code>python -m aishelf.db sync --rebuild</code>）后再来。</p>
  {% endif %}
  <script type="application/json" id="galaxies-data">{{ galaxies_json | tojson }}</script>
</section>
<script>
(function () {
  const resultEl = document.getElementById("result");
  const dataEl = document.getElementById("galaxies-data");
  if (!resultEl || !dataEl) return;
  let byCluster = {};
  try {
    JSON.parse(dataEl.textContent).forEach(g => { byCluster[g.id] = g.items || []; });
  } catch (e) { byCluster = {}; }

  function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }

  let busy = false;
  function render(cid, text) {
    const items = byCluster[cid] || [];
    const lines = text.split("\n");
    const html = lines.map(line => {
      const hit = items.find(it => it.title && line.indexOf(it.title) !== -1);
      if (!hit) return escapeHtml(line);
      const href = (hit.type === "video" ? "/videos/" : "/blogs/") + encodeURIComponent(hit.id);
      const esc = escapeHtml(line);
      return esc.replace(escapeHtml(hit.title),
        '<a href="' + href + '">' + escapeHtml(hit.title) + "</a>");
    }).join("<br>");
    resultEl.innerHTML = html;
  }

  async function run(cid, pill) {
    if (busy) return;
    busy = true;
    document.querySelectorAll(".lx-pill").forEach(p => p.classList.toggle("active", p === pill));
    resultEl.textContent = "正在规划路线…";
    let resp;
    try {
      resp = await fetch("/learn/route", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cluster_id: cid }),
      });
    } catch (e) { resultEl.textContent = "⚠️ 无法连接服务"; busy = false; return; }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "", acc = "", streaming = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n"); buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let p; try { p = JSON.parse(line.slice(6)); } catch (e) { continue; }
        if (p.delta) { if (!streaming) { streaming = true; acc = ""; } acc += p.delta; render(cid, acc); }
        else if (p.error) { resultEl.textContent = "⚠️ " + p.error; }
      }
    }
    busy = false;
  }

  document.querySelectorAll(".lx-pill").forEach(pill => {
    pill.addEventListener("click", () => run(parseInt(pill.getAttribute("data-cid"), 10), pill));
  });
})();
</script>
{% endblock %}
```

- [ ] **Step 3b: Add the nav link in `_topbar.html`** — change the `<nav>` line to add
`<a href="/learn">路线</a>` right after `<a href="/mirror">镜子</a>`:

```html
<nav><a href="/videos">视频</a><a href="/blogs">博客</a><a href="/write">写博客</a><a href="/ask">问答</a><a href="/graph">图谱</a><a href="/collide">碰撞</a><a href="/mirror">镜子</a><a href="/learn">路线</a><a href="/collect">Hermes</a></nav>
```

- [ ] **Step 3c: Append a `.learn` block to `static/style.css`:**

```css
/* 进阶路线 / 学习路径 */
.learn h2 .hint { font-size: .55em; font-weight: 400; color: #8a8f98; margin-left: .5em; }
.lx-pills { display: flex; flex-wrap: wrap; gap: .5rem; margin: 1rem 0; }
.lx-pill {
  cursor: pointer; font-size: .85rem; padding: .3rem .8rem; border-radius: 999px;
  color: var(--c); border: 1px solid var(--c);
  background: color-mix(in srgb, var(--c) 12%, transparent);
}
.lx-pill.active { background: color-mix(in srgb, var(--c) 28%, transparent); font-weight: 600; }
.learn-result {
  white-space: normal; line-height: 1.9; font-size: .95rem; margin-top: 1rem;
  padding: 1rem 1.2rem; border-radius: 12px;
  background: linear-gradient(135deg, rgba(56,225,192,.07), rgba(76,194,255,.06));
  border: 1px solid #2c313b;
}
.learn-result a { color: #8ab4ff; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_site_learn.py -v`
Expected: PASS (all). Then `python -m pytest -q` — whole suite green.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/templates/learn.html src/aishelf/site/templates/_topbar.html src/aishelf/site/static/style.css tests/unit/test_site_learn.py
git commit -m "feat(site): 进阶路线前端（星系药丸 + 流式课程 + 标题链接 + 路线导航）"
```

---

### Task 5: Docs — update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document `learn.py`** — add to the `aishelf/site/` module bullet list
(near `mirror.py`):

```
  `learn.py` (进阶路线: pure `build_messages` + tolerant `load_galaxies` — reads
  the `clusters`/`items` derived tables into galaxies-with-items and phrases an
  ordered 中文 学习路线 over a chosen galaxy; mirrors collide.py/mirror.py's split;
  streamed by `POST /learn/route`, no persistence/new config),
```

- [ ] **Step 2: Document the routes** — near the `/mirror` prose, add:

```
`GET /learn` renders the 进阶路线 page (server-rendered galaxy pills + embedded
per-galaxy item ids for client-side title→link matching); `POST /learn/route`
streams an ordered 入门→进阶→纵深 学习路线 over the chosen galaxy's items via
`llm.stream_completion` (ungated like /ask; unknown/empty cluster → error event).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 进阶路线/学习路径（learn.py + GET /learn + POST /learn/route）"
```

---

## Self-Review

**1. Spec coverage:**
- `learn.build_messages` (pure, ordered, title-prefixed steps) → Task 1 ✓
- `learn.load_galaxies` (single loader, galaxies-with-items, tolerant) → Task 2 ✓
- Routes `GET /learn` (server-render + embedded JSON) + `POST /learn/route`
  (`_LearnRequest`, error event, stream) → Task 3 ✓
- Frontend pills + title-link matching + empty state, topbar link, `.learn` CSS → Task 4 ✓
- Tests: build_messages, load_galaxies (+ degradation), routes (stream + error), page/topbar/pill → Tasks 1–4 ✓
- CLAUDE.md → Task 5 ✓
- Out-of-scope honored (no persistence, no progress/gamification, no new config/deps/DB) ✓

**2. Placeholder scan:** No TBD/TODO; every code step has full code. Task 1/2 notes
clarify the assertions. ✓

**3. Type consistency:** `Galaxy(id,name,color,size,items)` / `Item(id,title,summary,type)`
identical across Tasks 1–3. `load_galaxies(db_path) -> list[Galaxy]` used the same
way in both routes. `build_messages(galaxy_name, items_dicts)` — route builds
`item_dicts` with id/title/summary/type matching `_fmt_item`'s reads (title/type/summary).
JS posts `{cluster_id}` (matches `_LearnRequest`), reads `{galaxy}`/`{delta}`/`{error}`
events (route emits exactly those + `stream_completion`'s `done`), and links from
server-embedded `{id,title,type}` only. Pill `data-cid` is the int cluster id. ✓

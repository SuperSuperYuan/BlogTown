# 藏书镜 / 阅读画像 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an on-demand 「藏书镜」page that synthesizes the whole collection's theme galaxies into a streamed 中文 reading-persona portrait.

**Architecture:** A new leaf module `aishelf/site/mirror.py` follows the `collide.py`/`path.py` split — one tolerant DB loader (`load_profile`) + one pure prompt builder (`build_messages`). Two routes (`GET /mirror`, `POST /mirror/chat`) reuse `llm.stream_completion` + `hermes.sse`; a `mirror.html` template mirrors `collide.html`'s SSE-reading JS. No persistence, no new config, no sync-time work.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite (derived DB), pytest + FastAPI TestClient.

---

### Task 1: `mirror.py` — dataclasses + pure `build_messages`

**Files:**
- Create: `src/aishelf/site/mirror.py`
- Test: `tests/unit/test_site_mirror.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_site_mirror.py
from aishelf.site import mirror


def _profile():
    return mirror.Profile(
        galaxies=[
            mirror.Galaxy(name="推理模型", color="#ff9a3c", size=12, recent=4,
                          titles=["o1 深度解析", "测试时计算", "思维链评测"]),
            mirror.Galaxy(name="多模态", color="#4cc2ff", size=3, recent=0,
                          titles=["看图说话", "视频理解"]),
        ],
        total=15, videos=9, blogs=6,
        top_authors=[("Karpathy", 4), ("OpenAI", 3)],
        span_days=120, recent_n=10,
    )


def test_build_messages_shape_and_content():
    msgs = mirror.build_messages(_profile())
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    # the four bracketed sections are demanded, plain text only
    for tag in ["【你的主线】", "【最近的转向】", "【一个盲区】", "【一句话人格】"]:
        assert tag in system
    assert "Markdown" in system or "markdown" in system
    # user message grounds the model in real galaxy + corpus facts
    assert "推理模型" in user and "多模态" in user
    assert "12" in user and "o1 深度解析" in user
    assert "Karpathy" in user
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_site_mirror.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: module 'aishelf.site.mirror' has no attribute 'Profile'`.

- [ ] **Step 3: Write the dataclasses + `build_messages`**

```python
# src/aishelf/site/mirror.py
"""Collection-persona mirror (藏书镜): synthesize the whole collection's theme
galaxies into a 中文 reading-persona portrait.

Mirrors collide.py / path.py: one tolerant DB loader (load_profile) + one pure
prompt builder (build_messages). Reuses ATLAS_CHAT_* via the site llm client and
the clusters/items tables already built at sync time. On-demand, no persistence,
no new config.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from aishelf.db import schema


@dataclass
class Galaxy:
    name: str          # cluster name; "" when unnamed (alias pipeline off)
    color: str         # clusters.color — fact-strip pill colour (matches /graph)
    size: int          # member count
    recent: int        # members within the recent-N window (for 转向)
    titles: list[str]  # up to 5 sample member titles (grounding for the LLM)


@dataclass
class Profile:
    galaxies: list           # list[Galaxy], sorted by size desc
    total: int               # items with a cluster
    videos: int
    blogs: int
    top_authors: list        # list[tuple[str, int]], up to 3, blanks skipped
    span_days: int           # earliest→latest collected_at, 0 if unknown
    recent_n: int


def _fmt_galaxy(g: "Galaxy") -> str:
    name = g.name or "（未命名星系）"
    titles = "；".join(g.titles)
    return f"- {name}（{g.size} 条，最近 {g.recent} 条）：{titles}"


def build_messages(profile: "Profile") -> list[dict]:
    """System + user chat messages asking for the bracketed 中文 portrait.

    Pure — no DB, no LLM. `profile` is a Profile built by load_profile."""
    system = (
        "你是一面懂行又毒舌的镜子。用户会给你一份他收藏内容的画像数据——若干"
        "主题星系（每个有规模、最近活跃度、代表标题）以及整体统计。请据此读出这个"
        "人的阅读人格。输出恰好四段，每段以方括号小标题开头，再加结尾一句建议，"
        "具体、有锋芒、不要空话套话：\n"
        "【你的主线】挑 2-3 个最大的星系，每条 1-2 句，点破他在痴迷什么。\n"
        "【最近的转向】最近收藏相对整体偏向了什么；若无明显转向就直说没有。1-2 句。\n"
        "【一个盲区】最薄的那个星系，1-2 句，略带锋芒。\n"
        "【一句话人格】一句俏皮的人格速写。\n"
        "最后另起一行，给一句具体的下一步建议——只能从他已有的收藏延伸（补一补某个"
        "盲区，或顺着某条主线深挖），不要推荐站外的东西。\n"
        "只输出这些纯文本，不要使用 Markdown 语法（不要 # 或 * 等），"
        "不要额外的开场白或总结。"
    )
    gx = "\n".join(_fmt_galaxy(g) for g in profile.galaxies)
    authors = "、".join(f"{a}（{c}）" for a, c in profile.top_authors) or "（不详）"
    user = (
        f"主题星系（按规模从大到小）：\n{gx}\n\n"
        f"整体：共 {profile.total} 条（{profile.videos} 视频 / {profile.blogs} 博客），"
        f"收藏时间跨度约 {profile.span_days} 天，最近窗口取最新 {profile.recent_n} 条。\n"
        f"高频作者：{authors}。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_site_mirror.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/mirror.py tests/unit/test_site_mirror.py
git commit -m "feat(site): mirror.build_messages（阅读人格画像提示）"
```

---

### Task 2: `mirror.py` — `load_profile` DB loader

**Files:**
- Modify: `src/aishelf/site/mirror.py`
- Test: `tests/unit/test_site_mirror.py`

This task reads the derived DB. Tests build a DB directly via `aishelf.db.schema`
so they need no embeddings/LLM. The `items` table columns used: `id, type,
author, collected_at, title, cluster`. The `clusters` table: `id, name, color`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/unit/test_site_mirror.py
from aishelf.db import schema as db_schema


def _seed(db_path):
    con = db_schema.connect(db_path)
    db_schema.init_db(con)
    con.execute("INSERT INTO clusters (id, name, color, signature) VALUES (0,'推理','#ff9a3c','s0')")
    con.execute("INSERT INTO clusters (id, name, color, signature) VALUES (1,'多模态','#4cc2ff','s1')")
    rows = [
        ("v1", "video", "A", "2026-01-01T00:00:00", "推理一", 0),
        ("v2", "video", "A", "2026-02-01T00:00:00", "推理二", 0),
        ("b1", "blog",  "B", "2026-03-01T00:00:00", "推理三", 0),
        ("v3", "video", "B", "2026-05-01T00:00:00", "多模态一", 1),  # most recent
    ]
    for id_, type_, author, collected, title, cluster in rows:
        con.execute(
            "INSERT INTO items (id, type, title, author, collected_at, cluster) "
            "VALUES (?,?,?,?,?,?)",
            (id_, type_, title, author, collected, cluster),
        )
    con.commit()
    con.close()


def test_load_profile_aggregates(tmp_path):
    db = str(tmp_path / "atlas.db")
    _seed(db)
    p = mirror.load_profile(db, recent_n=2)
    assert p is not None
    # galaxies sorted by size desc: cluster 0 (3) before cluster 1 (1)
    assert [g.name for g in p.galaxies] == ["推理", "多模态"]
    assert [g.size for g in p.galaxies] == [3, 1]
    # recent window = newest 2 items (v3 cluster1, b1 cluster0)
    by_name = {g.name: g for g in p.galaxies}
    assert by_name["多模态"].recent == 1
    assert by_name["推理"].recent == 1
    assert p.total == 4 and p.videos == 3 and p.blogs == 1
    assert p.galaxies[0].titles  # has sample titles
    assert by_name["多模态"].color == "#4cc2ff"
    assert p.span_days >= 1


def test_load_profile_none_when_no_clusters(tmp_path):
    db = str(tmp_path / "atlas.db")
    con = db_schema.connect(db)
    db_schema.init_db(con)
    con.execute("INSERT INTO items (id, type, title) VALUES ('x','video','t')")
    con.commit(); con.close()
    assert mirror.load_profile(db) is None


def test_load_profile_none_when_db_missing(tmp_path):
    assert mirror.load_profile(str(tmp_path / "nope.db")) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_site_mirror.py -k load_profile -v`
Expected: FAIL with `AttributeError: module 'aishelf.site.mirror' has no attribute 'load_profile'`.

- [ ] **Step 3: Implement `load_profile`**

Add to `src/aishelf/site/mirror.py`:

```python
def _collected_key(raw: str):
    """ISO collected_at -> naive-UTC datetime; unparseable sorts last.

    Same tolerant logic as digest._collected_key (kept local so mirror stays a
    leaf module — no cross-import)."""
    try:
        dt = datetime.fromisoformat(raw or "")
    except ValueError:
        return datetime.min
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def load_profile(db_path, *, recent_n: int = 10):
    """Build a Profile from the derived DB, or None when there are no clustered
    items / no DB. Tolerant of a missing/old DB (returns None, never raises) —
    same posture as db.search.hooks_for / collide.load_pair_space."""
    try:
        con = schema.connect(db_path)
        try:
            schema.init_db(con)
            clusters = {
                r["id"]: (r["name"] or "", r["color"] or "")
                for r in con.execute("SELECT id, name, color FROM clusters")
            }
            rows = con.execute(
                "SELECT id, type, author, collected_at, title, cluster "
                "FROM items WHERE cluster IS NOT NULL"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not rows:
        return None

    ordered = sorted(
        rows, key=lambda r: (_collected_key(r["collected_at"] or ""), r["id"]),
        reverse=True,
    )
    recent_ids = {r["id"] for r in ordered[:recent_n]}

    by_cluster: dict[int, list] = {}
    for r in rows:
        by_cluster.setdefault(r["cluster"], []).append(r)

    galaxies = []
    for cid, members in by_cluster.items():
        name, color = clusters.get(cid, ("", ""))
        recent = sum(1 for m in members if m["id"] in recent_ids)
        titles = [m["title"] for m in members[:5]]
        galaxies.append(Galaxy(name=name, color=color, size=len(members),
                               recent=recent, titles=titles))
    galaxies.sort(key=lambda g: (-g.size, g.name))

    videos = sum(1 for r in rows if r["type"] == "video")
    blogs = sum(1 for r in rows if r["type"] == "blog")

    author_counts: dict[str, int] = {}
    for r in rows:
        a = (r["author"] or "").strip()
        if a:
            author_counts[a] = author_counts.get(a, 0) + 1
    top_authors = sorted(author_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]

    dts = [_collected_key(r["collected_at"] or "") for r in rows]
    dts = [d for d in dts if d != datetime.min]
    span_days = (max(dts) - min(dts)).days if len(dts) >= 2 else 0

    return Profile(galaxies=galaxies, total=len(rows), videos=videos, blogs=blogs,
                   top_authors=top_authors, span_days=span_days, recent_n=recent_n)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_site_mirror.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/mirror.py tests/unit/test_site_mirror.py
git commit -m "feat(site): mirror.load_profile（从派生库读收藏画像）"
```

---

### Task 3: Routes `GET /mirror` + `POST /mirror/chat`

**Files:**
- Modify: `src/aishelf/site/app.py` (import `mirror`; add `_profile_payload` near `_collide_ref` ~line 110; add 2 routes after the `/collide` routes ~line 461)
- Modify: `src/aishelf/site/templates/mirror.html` (created in Task 4 — but `GET /mirror` route returns it; create a minimal stub here so the route test passes, Task 4 fleshes it out)
- Test: `tests/unit/test_site_mirror.py`

- [ ] **Step 1: Write the failing route tests**

```python
# add to tests/unit/test_site_mirror.py
import aishelf.site.app as app_module
from aishelf.site.app import app
from fastapi.testclient import TestClient


def test_mirror_page_renders():
    client = TestClient(app)
    r = client.get("/mirror")
    assert r.status_code == 200
    assert "藏书镜" in r.text


def test_mirror_chat_streams_profile_then_deltas(tmp_path, monkeypatch):
    # default DB path is <data_dir>/atlas.db, so seed directly there
    _seed(str(tmp_path / "atlas.db"))
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_module.llm, "stream_completion",
                        lambda messages: iter([app_module.hermes.sse({"delta": "你是"}),
                                               app_module.hermes.sse({"done": True})]))
    client = TestClient(app)
    body = client.post("/mirror/chat").text
    assert '"profile"' in body
    assert "推理" in body          # galaxy name in the profile payload
    assert "你是" in body          # streamed delta


def test_mirror_chat_error_when_no_clusters(tmp_path, monkeypatch):
    monkeypatch.setenv("AISHELF_DATA_DIR", str(tmp_path))
    con = db_schema.connect(str(tmp_path / "atlas.db"))
    db_schema.init_db(con)
    con.execute("INSERT INTO items (id, type, title) VALUES ('x','video','t')")
    con.commit(); con.close()
    client = TestClient(app)
    body = client.post("/mirror/chat").text
    assert '"error"' in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_site_mirror.py -k mirror_page -v`
Expected: FAIL — `GET /mirror` 404 (no route / no template).

- [ ] **Step 3a: Create a minimal `mirror.html` stub** (Task 4 fleshes it out)

```html
<!-- src/aishelf/site/templates/mirror.html -->
{% extends "base.html" %}
{% block content %}
<section class="mirror"><h2>藏书镜</h2></section>
{% endblock %}
```

- [ ] **Step 3b: Add `_profile_payload` helper near `_collide_ref` (~line 110 in app.py)**

```python
def _profile_payload(profile) -> dict:
    """Compact, escapable fact strip for the /mirror page (mirrors _collide_ref)."""
    return {
        "galaxies": [{"name": g.name, "color": g.color, "size": g.size}
                     for g in profile.galaxies],
        "total": profile.total, "videos": profile.videos, "blogs": profile.blogs,
        "span_days": profile.span_days,
        "top_author": profile.top_authors[0][0] if profile.top_authors else "",
    }
```

- [ ] **Step 3c: Add `mirror` to the `aishelf.site` import block (~line 27-43 in app.py)**

Add `mirror,` to the alphabetized import list (after `markdown,`).

- [ ] **Step 3d: Add the two routes after the `/collide/chat` route (~line 461)**

```python
@app.get("/mirror", response_class=HTMLResponse)
def mirror_page(request: Request):
    return templates.TemplateResponse(request, "mirror.html", {})


@app.post("/mirror/chat")
def mirror_chat():
    # Ungated: synthesis is cheap (like /ask and /collide), not the Hermes path.
    profile = mirror.load_profile(default_db_path(get_data_dir()))

    def _gen():
        if profile is None:
            yield hermes.sse({"error": "先采集一些内容并同步图谱，才能照镜子"})
            yield hermes.sse({"done": True})
            return
        yield hermes.sse({"profile": _profile_payload(profile)})
        yield from llm.stream_completion(mirror.build_messages(profile))

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_site_mirror.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/app.py src/aishelf/site/templates/mirror.html tests/unit/test_site_mirror.py
git commit -m "feat(site): GET /mirror + POST /mirror/chat（藏书镜流式画像）"
```

---

### Task 4: Frontend — `mirror.html` + topbar link + CSS

**Files:**
- Modify: `src/aishelf/site/templates/mirror.html` (replace the stub)
- Modify: `src/aishelf/site/templates/_topbar.html` (nav link)
- Modify: `src/aishelf/site/static/style.css` (small `.mirror` block)
- Test: `tests/unit/test_site_mirror.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/unit/test_site_mirror.py
def test_topbar_has_mirror_link():
    client = TestClient(app)
    r = client.get("/mirror")
    assert 'href="/mirror"' in r.text


def test_mirror_page_has_action_button():
    client = TestClient(app)
    r = client.get("/mirror")
    assert "照一照" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_site_mirror.py -k "topbar or action_button" -v`
Expected: FAIL — stub has no button, topbar has no link.

- [ ] **Step 3a: Replace `mirror.html` with the full page**

```html
<!-- src/aishelf/site/templates/mirror.html -->
{% extends "base.html" %}
{% block content %}
<section class="mirror">
  <h2>藏书镜 <span class="hint">照一照你的收藏，看看你是谁</span></h2>
  <div class="mirror-facts" id="facts"></div>
  <div class="mirror-controls"><button id="again" type="button">照一照 ↻</button></div>
  <div class="mirror-result" id="result"></div>
</section>
<script>
(function () {
  const factsEl = document.getElementById('facts');
  const resultEl = document.getElementById('result');
  const againBtn = document.getElementById('again');
  let busy = false;

  function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
  function safeColor(c) { return /^#[0-9a-fA-F]{6}$/.test(c || '') ? c : '#888'; }

  function renderFacts(p) {
    const pills = (p.galaxies || []).map(g =>
      '<span class="mx-pill" style="--c:' + safeColor(g.color) + '">'
      + escapeHtml(g.name || '未命名') + ' · ' + (g.size | 0) + '</span>').join('');
    const line = (p.total | 0) + ' 条 · ' + (p.videos | 0) + ' 视频 · ' + (p.blogs | 0) + ' 博客'
      + (p.span_days ? ' · 跨度 ' + (p.span_days | 0) + ' 天' : '')
      + (p.top_author ? ' · 常客 ' + escapeHtml(p.top_author) : '');
    factsEl.innerHTML = '<div class="mx-pills">' + pills + '</div><div class="mx-line">' + line + '</div>';
  }

  async function run() {
    if (busy) return;
    busy = true; againBtn.disabled = true; resultEl.textContent = '正在照镜子…';
    let resp;
    try {
      resp = await fetch('/mirror/chat', { method: 'POST' });
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
        if (p.profile) { renderFacts(p.profile); }
        else if (p.delta) { if (!streaming) { streaming = true; acc = ''; resultEl.textContent = ''; } acc += p.delta; resultEl.textContent = acc; }
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

- [ ] **Step 3b: Add the nav link in `_topbar.html`** (after the `/collide` link)

Change the `<nav>` line to include `<a href="/mirror">镜子</a>` right after `<a href="/collide">碰撞</a>`:

```html
<nav><a href="/videos">视频</a><a href="/blogs">博客</a><a href="/write">写博客</a><a href="/ask">问答</a><a href="/graph">图谱</a><a href="/collide">碰撞</a><a href="/mirror">镜子</a><a href="/collect">Hermes</a></nav>
```

- [ ] **Step 3c: Append a `.mirror` block to `static/style.css`**

```css
/* 藏书镜 / 阅读画像 */
.mirror h2 .hint { font-size: .6em; font-weight: 400; color: #8a8f98; margin-left: .5em; }
.mirror-facts { margin: 1rem 0; }
.mx-pills { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .4rem; }
.mx-pill {
  font-size: .8rem; padding: .15rem .6rem; border-radius: 999px;
  color: var(--c); border: 1px solid var(--c);
  background: color-mix(in srgb, var(--c) 12%, transparent);
}
.mx-line { font-size: .85rem; color: #8a8f98; }
.mirror-controls { margin: .5rem 0 1rem; }
.mirror-controls button {
  cursor: pointer; border-radius: 8px; border: 1px solid #3a3f4b;
  background: #20242c; color: #e6e8eb; padding: .4rem .9rem;
}
.mirror-controls button:disabled { opacity: .5; cursor: default; }
.mirror-result {
  white-space: pre-wrap; line-height: 1.7; font-size: .95rem;
  padding: 1rem 1.2rem; border-radius: 12px;
  background: linear-gradient(135deg, rgba(192,140,255,.08), rgba(76,194,255,.06));
  border: 1px solid #2c313b;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_site_mirror.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/aishelf/site/templates/mirror.html src/aishelf/site/templates/_topbar.html src/aishelf/site/static/style.css tests/unit/test_site_mirror.py
git commit -m "feat(site): 藏书镜前端（事实条 + 流式人格 + 镜子导航）"
```

---

### Task 5: Docs — update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document `mirror.py`** — add to the `aishelf/site/` module bullet list (near `digest.py`):

```
  `mirror.py` (藏书镜: pure `build_messages` + tolerant `load_profile` — reads the
  `clusters`/`items` derived tables into a Profile of theme galaxies + corpus
  stats; mirrors collide.py/digest.py's pure-logic split; no LLM/persistence),
```

- [ ] **Step 2: Document the routes** — in the derived-DB / endpoints prose, add a sentence near the `/collide` description:

```
`GET /mirror` renders the 藏书镜 page; `POST /mirror/chat` builds a collection
profile from the theme galaxies and streams a 中文 阅读人格 portrait (主线/转向/盲区/
人格 + 一条收藏内建议); degrades to a friendly empty state when no clusters exist.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 藏书镜/阅读画像（mirror.py + GET /mirror + POST /mirror/chat）"
```

---

## Self-Review

**1. Spec coverage:**
- `mirror.py` load_profile + build_messages + dataclasses → Tasks 1–2 ✓
- Routes `GET /mirror` + `POST /mirror/chat` + `_profile_payload`, ungated, empty-state error → Task 3 ✓
- `mirror.html` (facts strip + button + streamed portrait, escaping, color validation) → Task 4 ✓
- topbar link → Task 4 ✓
- CSS `.mirror` in `style.css` → Task 4 ✓
- Tests: build_messages, load_profile aggregation + degradation, route stream + error, page/topbar → Tasks 1–4 ✓
- CLAUDE.md → Task 5 ✓
- Out-of-scope items (no persistence, no keyword fallback, no drill-down) honored — no tasks add them ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows full code. Task 3 Step 1 includes a self-correcting note that resolves to the simplified `_seed(str(tmp_path/"atlas.db"))` form — the engineer uses the rewritten version. ✓

**3. Type consistency:** `Profile`/`Galaxy` fields are identical across Tasks 1–3 (`name, color, size, recent, titles`; `galaxies, total, videos, blogs, top_authors, span_days, recent_n`). `load_profile(db_path, *, recent_n=10)` signature consistent in Tasks 2–3. `_profile_payload` reads only fields that exist. JS reads `profile.galaxies[].{name,color,size}`, `total/videos/blogs/span_days/top_author` — all emitted by `_profile_payload`. ✓

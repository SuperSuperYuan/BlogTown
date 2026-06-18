# 图谱 C 节点详情侧栏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/graph` 单击节点时弹出页内详情侧栏（取代新开标签页），展示标题/钩子/摘要/关键词/笔记 + 可点的"语义相邻"邻居，并联动星图高亮；侧栏数据来自一个新的只读 `GET /api/item/{id}` + 前端已有的 `adj` 邻接表。

**Architecture:** 两块边界清晰：① 后端瘦路由 `GET /api/item/{id}`（逻辑在 `_item_detail` helper）；② `graph.html` 内轻量侧栏子系统 `openPanel`/`closePanel`，复用 `adj`/`nodeMeshes`/`restoreAll`/`controls`，不进 MODES 体系。

**Tech Stack:** FastAPI / Pydantic / Jinja2 / Three.js r128（CDN，已在）/ pytest。

**关键事实（已核对当前代码）：**
- `app.py` 已 `from aishelf.site import (... items, llm, markdown, ...)`；有 `_items()`（按 data_dir 加载内容）、`_note_for(item)`（取笔记，id 不安全时返回 ""）、`_item_dict`（碰撞用，勿混淆）。
- item 字段：`id/type/title/author/platform/source_url/published_at/summary/keywords(list)/collected_at`（video 另有 thumbnail_url 等；blog 另有 cover_image_url/body/origin）。
- `items.safe_id(id)` 路径不安全时 **raise ValueError**。
- `markdown.render_markdown(text)` → sanitized HTML，空串 → ""，永不抛错。
- `graph.html`：节点循环里已设 `n.href`（`/videos|blogs/{id}`，第 164 行）；`adj`（id→[{id,w}]）、`meshOf`、`nodeMeshes`、`restoreAll()`、`controls`、`currentMode`、`CLUSTER_COLOR` 均已存在；rest 态 canvas click 当前是 `window.open`；`setMode(name)` 在第 325 行。
- 测试 fixture 模式见 `tests/unit/test_site_notes_routes.py`：`shutil.copytree(FIXTURES, data)` + `monkeypatch.setenv("AISHELF_DATA_DIR", ...)`；fixture 内容 id：视频 `youtube-aaa`、`bilibili-bbb`，博客 `blog-ccc`、`blog-ddd`。

---

## File Structure

**修改**
- `src/aishelf/site/app.py` — `_item_detail` helper + `GET /api/item/{id}` 路由。
- `src/aishelf/site/templates/graph.html` — `#nodePanel` DOM/CSS + `openPanel`/`closePanel` + click 改写 + Esc + `setMode` 关闭钩子。
- `CLAUDE.md` — 记录新端点 + 节点侧栏。

**新增**
- `tests/unit/test_site_item_route.py` — `/api/item/{id}` 路由测试。

---

## Task 1: 后端 `GET /api/item/{id}` + `_item_detail`

**Files:**
- Modify: `src/aishelf/site/app.py`
- Test: `tests/unit/test_site_item_route.py`

- [ ] **Step 1: 写失败测试**（新建 `tests/unit/test_site_item_route.py`）

```python
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    from aishelf.site.app import app
    return TestClient(app)


def test_api_item_returns_detail(client):
    r = client.get("/api/item/youtube-aaa")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "youtube-aaa"
    assert set(["id", "type", "title", "author", "published_at",
                "summary", "keywords", "note_html"]).issubset(body.keys())
    assert isinstance(body["keywords"], list)


def test_api_item_unknown_is_404(client):
    assert client.get("/api/item/nope-zzz").status_code == 404


def test_api_item_unsafe_id_is_404(client):
    # safe_id rejects ".." -> route returns 404, never touches the filesystem
    assert client.get("/api/item/a..b").status_code == 404


def test_api_item_no_note_is_empty_html(client):
    body = client.get("/api/item/blog-ccc").json()
    assert body["note_html"] == ""


def test_api_item_renders_note_markdown(client):
    client.post("/notes/youtube-aaa", json={"text": "**重点** 段落"})
    body = client.get("/api/item/youtube-aaa").json()
    assert "<strong>" in body["note_html"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/test_site_item_route.py -v`
Expected: FAIL（404 for all — route missing）。

- [ ] **Step 3: 加 `_item_detail` helper**（`app.py`，放在现有 `_item_dict` 之后）

```python
def _item_detail(it, note: str) -> dict:
    """JSON detail for the /graph node panel: contract fields the graph payload
    omits, plus the user's note rendered to sanitized HTML."""
    return {
        "id": it.id, "type": it.type, "title": it.title, "author": it.author,
        "published_at": it.published_at, "summary": it.summary,
        "keywords": list(it.keywords),
        "note_html": markdown.render_markdown(note),
    }
```

- [ ] **Step 4: 加路由**（`app.py`，放在 `@app.post("/graph/path")` 路由之后）

```python
@app.get("/api/item/{id}")
def api_item(id: str):
    """Read-only per-item detail for the /graph node panel. 404 on unknown or
    path-unsafe id; ungated like the rest of browsing."""
    try:
        items.safe_id(id)
    except ValueError:
        raise HTTPException(status_code=404)
    it = next((x for x in _items() if x.id == id), None)
    if it is None:
        raise HTTPException(status_code=404)
    return _item_detail(it, _note_for(it))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/unit/test_site_item_route.py -v`
Expected: PASS（5/5）。

- [ ] **Step 6: 提交**

```bash
git add src/aishelf/site/app.py tests/unit/test_site_item_route.py
git commit -m "feat(site): GET /api/item/{id}（节点详情侧栏数据）"
```

---

## Task 2: 前端节点详情侧栏（`graph.html`，手动验证）

**Files:**
- Modify: `src/aishelf/site/templates/graph.html`

> 无自动化测试。每步定向编辑现有文件；改完用 `node --check` + jinja parse + 浏览器实测。

- [ ] **Step 1: CSS**（追加到 `<style>` 末尾，`</style>` 前）

```css
  .node-panel { position: absolute; right: 16px; top: 68px; bottom: 16px; width: 312px;
    display: none; flex-direction: column; background: rgba(8,14,28,.96);
    border: 1px solid #24365f; border-radius: 12px; padding: 14px 15px; z-index: 3;
    color: #e7eefb; font-size: 13px; line-height: 1.6; overflow: auto; }
  .node-panel.show { display: flex; }
  .np-x { position: absolute; right: 12px; top: 10px; color: #7f93bd; cursor: pointer; font-size: 15px; }
  .np-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  .np-badge { font-size: 11px; padding: 1px 8px; border-radius: 999px; background: #16263f; color: #bcd4ff; }
  .np-gchip { font-size: 11px; padding: 1px 8px; border-radius: 999px; display: inline-flex; align-items: center; gap: 5px; color: #cdd8ef; background: #0c1426; border: 1px solid #1d2a48; }
  .np-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: #4cc2ff; }
  .np-title { font-size: 16px; font-weight: 700; color: #eaf2ff; margin: 2px 0 8px; line-height: 1.4; }
  .np-hook { color: #a9c7ff; font-style: italic; margin-bottom: 6px; }
  .np-lbl { font-size: 11px; letter-spacing: .06em; color: #5f6f93; text-transform: uppercase; margin: 12px 0 4px; }
  .np-sum { color: #c3d0ea; }
  .np-kw { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
  .np-kw span { font-size: 11px; padding: 1px 7px; border-radius: 6px; background: #111c33; color: #9fb6e0; }
  .np-note { background: #0c1426; border: 1px solid #1d2a48; border-radius: 8px; padding: 8px 10px; color: #d7e2f7; }
  .np-note p { margin: 0 0 6px; }
  .np-nbr { display: flex; align-items: center; gap: 7px; padding: 4px 0; cursor: pointer; color: #cdd8ef; }
  .np-nbr:hover { color: #fff; }
  .np-nbr .w { margin-left: auto; font-size: 11px; color: #5f6f93; }
  .np-open { margin-top: 14px; color: #6cf0ff; text-decoration: none; }
```

- [ ] **Step 2: HTML 骨架**（在 `#pathPanel` 的 `</div>` 之后、`#globeTip` 之前加）

```html
  <div class="node-panel" id="nodePanel">
    <span class="np-x" id="panelClose">✕</span>
    <div class="np-head" id="pHead"></div>
    <div class="np-title" id="pTitle"></div>
    <div class="np-hook" id="pHook"></div>
    <div class="np-lbl">摘要</div>
    <div class="np-sum" id="pSummary">—</div>
    <div class="np-kw" id="pKeywords"></div>
    <div class="np-lbl">我的笔记</div>
    <div class="np-note" id="pNote">—</div>
    <div class="np-lbl">相关（语义相邻）</div>
    <div id="pNeighbors"></div>
    <a class="np-open" id="pOpen" target="_self">打开完整页面 →</a>
  </div>
```

- [ ] **Step 3: JS — 侧栏子系统。** 在 `MODES.path = function () {...};` 整段之后、`function resize()` 之前插入：

```javascript
  // ---- C 节点详情侧栏（不属于 MODES；只在静止态打开） ----
  const nodeById = {};
  for (const n of data.nodes) nodeById[n.id] = n;
  const clusterMeta = {};
  for (const c of (data.clusters || [])) clusterMeta[c.id] = { name: c.name || ('星系 ' + c.id), color: c.color || '#888' };
  const _panel = document.getElementById('nodePanel');

  function _esc(s) {                       // text -> safe HTML text
    return String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function openPanel(id) {
    const n = nodeById[id];
    if (!n) return;
    // head: type badge + galaxy chip
    const cm = clusterMeta[n.cluster];
    document.getElementById('pHead').innerHTML =
      '<span class="np-badge">' + (n.type === 'video' ? '视频' : '博客') + '</span>'
      + (cm ? '<span class="np-gchip"><span class="np-dot" style="background:' + cm.color + '"></span>' + _esc(cm.name) + '</span>' : '');
    document.getElementById('pTitle').textContent = n.title || '';
    const hk = document.getElementById('pHook');
    hk.textContent = n.hook || ''; hk.style.display = n.hook ? 'block' : 'none';
    document.getElementById('pOpen').href = n.href;
    // neighbors from the visible edge graph, strongest first
    const nbrs = (adj[id] || []).slice().sort((a, b) => b.w - a.w);
    document.getElementById('pNeighbors').innerHTML = nbrs.length ? nbrs.map((e) => {
      const nb = nodeById[e.id]; if (!nb) return '';
      const c = clusterMeta[nb.cluster];
      const lbl = nb.alias || (nb.title && nb.title.length > 12 ? nb.title.slice(0, 12) + '…' : nb.title || nb.id);
      return '<div class="np-nbr" data-id="' + _esc(e.id) + '"><span class="np-dot" style="background:'
        + (c ? c.color : '#888') + '"></span>' + _esc(lbl) + '<span class="w">' + e.w.toFixed(2) + '</span></div>';
    }).join('') : '<div class="np-sum">（暂无语义相邻）</div>';
    // placeholders while fetching detail
    document.getElementById('pSummary').textContent = '加载中…';
    document.getElementById('pKeywords').innerHTML = '';
    document.getElementById('pNote').textContent = '—';
    // highlight selected + neighbors, dim the rest, pause auto-rotate
    const keep = new Set([id, ...nbrs.map((e) => e.id)]);
    for (const m of nodeMeshes) {
      const on = keep.has(m.userData.id);
      m.material.opacity = on ? 1 : 0.12;
      if (m.userData._label) m.userData._label.element.style.opacity = on ? '1' : '0.12';
    }
    controls.autoRotate = false;
    _panel.classList.add('show');
    // fetch the rest (summary / keywords / note); failure leaves placeholders
    fetch('/api/item/' + encodeURIComponent(id)).then((r) => r.ok ? r.json() : null).then((d) => {
      if (!d || !_panel.classList.contains('show')) return;
      document.getElementById('pSummary').textContent = d.summary || '—';
      document.getElementById('pKeywords').innerHTML = (d.keywords || []).map((k) => '<span>' + _esc(k) + '</span>').join('');
      document.getElementById('pNote').innerHTML = d.note_html || '<span class="np-sum">（还没有笔记）</span>';
    }).catch(() => { document.getElementById('pSummary').textContent = '—'; });
  }

  function closePanel() {
    if (!_panel.classList.contains('show')) return;
    _panel.classList.remove('show');
    restoreAll();
    if (!currentMode) controls.autoRotate = true;
  }

  document.getElementById('panelClose').addEventListener('click', closePanel);
  document.getElementById('pNeighbors').addEventListener('click', (e) => {
    const row = e.target.closest('.np-nbr'); if (row && row.dataset.id) openPanel(row.dataset.id);
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePanel(); });
```

- [ ] **Step 4: JS — 改写 rest 态 click（取代 window.open）。** 现有：

```javascript
  renderer.domElement.addEventListener('click', () => {
    if (currentMode === 'path') return;   // path mode owns clicks (star picking)
    if (hovered && hovered.userData.href) window.open(hovered.userData.href, '_blank', 'noopener');
  });
```
改为：
```javascript
  renderer.domElement.addEventListener('click', () => {
    if (currentMode) return;              // verbs own clicks while active (path picks stars)
    if (hovered) openPanel(hovered.userData.id);
    else closePanel();                    // click empty space -> close
  });
```

- [ ] **Step 5: JS — 进入动词模式时关闭侧栏。** 现有 `setMode` 第一行之后插入 `closePanel();`：

```javascript
  function setMode(name) {
    closePanel();                          // a verb takes over -> drop the node panel
    if (currentMode === name) { leaveMode(); return; }   // toggle off
    leaveMode();
```
（`closePanel` 是函数声明，已 hoist，可在此处调用。）

- [ ] **Step 6: 静态校验**

```bash
python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('src/aishelf/site/templates')).get_template('graph.html'); print('jinja OK')"
python - <<'PY'
import re, subprocess
b=re.findall(r'<script>(.*?)</script>', open('src/aishelf/site/templates/graph.html',encoding='utf-8').read(), re.S)[-1]
open('/tmp/g.js','w').write(b); print('node --check rc', subprocess.run(['node','--check','/tmp/g.js']).returncode)
PY
python -m pytest tests/unit/test_site_graph_routes.py tests/unit/test_site_item_route.py -q
```
Expected: jinja OK；`node --check rc 0`；测试 PASS。

- [ ] **Step 7: 手动验证**（`python -m aishelf.site`，需含数据的 DB；先 `sync --rebuild`）：
  1. 静止态单击一颗星 → 右侧滑出侧栏（type 徽章 + 星系 chip + 标题 + 钩子 + 摘要 + 关键词 + 笔记 + 相关列表 + "打开完整页面"链接）；选中 + 邻居亮、其余变暗、停止自转。
  2. 点"相关"里的一项 → 侧栏切到那颗星、高亮随之更新。
  3. ✕ / 按 Esc / 点画布空白处 → 侧栏关闭、星图还原、恢复自转。
  4. "打开完整页面 →" → 跳到 `/videos|blogs/{id}`。
  5. 点底部「▶ 回放 / 🛸 逛逛 / 🔗 路径」任一 → 侧栏先关闭再进入该模式；路径模式选星不会弹侧栏。

- [ ] **Step 8: 提交**

```bash
git add src/aishelf/site/templates/graph.html
git commit -m "feat(graph): C 节点详情侧栏（点星弹页内侧栏 + 邻居导航 + 联动高亮）"
```

---

## Task 3: 文档同步（CLAUDE.md）

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新 `/graph` 描述** — 补一句：静止态单击节点弹出页内详情侧栏（标题/钩子/摘要/关键词/笔记 + 可点的语义相邻邻居 + 联动高亮变暗 + 暂停自转；✕/Esc/空白关闭；进入动词模式会关闭它），取代原"点节点新开标签页"。

- [ ] **Step 2: 记录新端点** — 在路由清单处加 `GET /api/item/{id}`（只读 per-item 详情：摘要/作者/关键词 + 渲染后的笔记 HTML，供 `/graph` 侧栏；`safe_id` 守卫 + 未知/不安全 id → 404）。

- [ ] **Step 3: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: 图谱节点详情侧栏 + /api/item/{id}"
```

---

## Final Verification

- [ ] `pytest` → 全绿（新增 5 个路由测试，无回归）。
- [ ] `node --check`（见 Task 2 Step 6）对最终 `graph.html` 通过。
- [ ] 手动：Task 2 Step 7 的清单逐项过一遍（含与三个动词模式的互斥）。

---

## Self-Review（已核对）

- **Spec 覆盖**：触发=单击取代新标签页 → Task 2 Step 4；联动高亮+暂停自转 → Step 3 openPanel；✕/Esc/空白关闭 → Step 3 + Step 4；邻居可点导航 → Step 3 委托监听；与模式互斥 → Step 5；`GET /api/item/{id}`（safe_id+404+note_html）→ Task 1；文档 → Task 3。
- **占位符**：无 TBD；每个代码步骤给出完整代码。
- **命名/类型一致**：`_item_detail(it, note)` 返回的键与 Task 1 测试断言一致、与前端 `openPanel` 消费的 `d.summary/d.keywords/d.note_html` 一致；`openPanel`/`closePanel` 在 Step 3 定义、Step 4/5 调用；DOM id（`pHead/pTitle/pHook/pSummary/pKeywords/pNote/pNeighbors/pOpen/panelClose/nodePanel`）在 Step 2 与 Step 3 一一对应；复用的 `adj/nodeMeshes/restoreAll/currentMode/controls/nodeById/n.href` 均为现有或本任务新建。
- **安全**：侧栏所有动态文本经 `_esc()`（笔记 `note_html` 已由后端 nh3 sanitize，直接 innerHTML 安全）。
- **已知边界**：前端侧栏无自动化测试（与现有 `graph.html` 一致，靠 `node --check` + 浏览器实测）；需含 embedding 的 DB 才有邻居（无边时"相关"显示"暂无语义相邻"，侧栏其余照常）。

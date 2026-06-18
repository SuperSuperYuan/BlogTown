# 图谱 · C 节点详情侧栏 — 设计文档

**日期：** 2026-06-18
**状态：** 设计已确认，待写实现计划
**范围：** `/graph` 页面，单个聚焦特性（一个新只读后端 + `graph.html` 前端侧栏）

## 目标

在 `/graph` 点一颗星时，**在页内右侧滑出一个详情侧栏**展示该内容（取代当前"新开标签页"的
`window.open`），让人不离开星图就能读到标题、钩子、摘要、自己的笔记，以及"语义相邻"的内容，
并能顺着邻居在侧栏间跳转。严守「简洁 + 实用 + 好玩，distill not decorate」：侧栏是星图静止态的
自然延伸，不是新"模式"，不堆控件。

## UX 决策（已确认）

- **触发**：静止态（无激活动词模式）单击节点 → 打开侧栏，**取代新开标签页**。
- **联动星图**：打开时，选中节点 + 它的"相关"邻居常亮，其余节点变暗（opacity 0.12），
  并**暂停自动旋转**（选中星不漂走）；关闭时还原。
- **关闭**：✕ 按钮、`Esc` 键、点画布空白处（raycast 无命中）——三者都保留。
- **邻居可点**：侧栏的"相关"列表项点击 → 切换到那颗星的侧栏。
- **不是模式**：侧栏独立于 verb-pill 的 MODES 体系；进入任一动词模式（回放/漫游/路径）会先关闭侧栏。
- **完整页面**：底部"打开完整页面 →"链接到站内详情页 `/videos/{id}` 或 `/blogs/{id}`
  （外链在详情页里，侧栏不重复）。

## 架构

两块，边界清晰：

1. **后端**：新增只读 `GET /api/item/{id}`，返回侧栏需要、但 `/api/graph` 没带的字段
   （摘要/作者/关键词/已渲染笔记）。路由瘦，逻辑在一个小 helper。
2. **前端**：`graph.html` 内一套轻量侧栏子系统 `openPanel(id)` / `closePanel()`，
   复用已有的 `adj` 邻接表、节点表、`restoreAll()`、`controls`。

数据来源拆分：
- **节点已有**（`/api/graph`）：`id/type/title/alias/cluster/hook/degree`。
- **按需拉取**（`/api/item/{id}`）：`author/published_at/summary/keywords/note_html`。
- **邻居**：前端 `adj[id]`（top-K 截断后的可见边集）+ 节点表，**无需后端**；相似度直接用边 `weight`。

## 后端：`GET /api/item/{id}`

```
GET /api/item/{id}
  200 →
  {
    "id": str, "type": str, "title": str, "author": str,
    "published_at": str, "summary": str, "keywords": [str, ...],
    "note_html": str            # markdown.render_markdown(note)；无笔记则 ""
  }
  404 → 未找到该 id
```

- `id` 先过 `items.safe_id`（路径安全的唯一choke point，与 notes/delete 一致）。
- 内容查找复用 `_items()`（按 id 匹配，video 或 blog 皆可）；笔记复用 `_note_for(item)`。
- `note_html` 经 `markdown.render_markdown`（markdown-it-py + nh3 sanitize，永不抛错）。
- 纯读、无副作用、**不受采集口令限制**（与浏览/`/ask`/`/api/graph` 一样开放）。
- 路由只做：`safe_id` → 查找 → 404 或序列化。序列化逻辑提到一个小 helper
  `_item_detail(item, note) -> dict`，保持路由瘦、helper 可独立测。

## 前端：侧栏子系统（`graph.html`）

**DOM**（新增，复用暗色主题 + path-panel 的定位风格）：
- `#nodePanel`（右侧栏，可滚动），内含：✕、type 徽章 + 星系 chip、标题、钩子、摘要、关键词 chips、
  「我的笔记」块、「相关（语义相邻）」列表、底部「打开完整页面 →」链接。

**`openPanel(id)`**：
1. `closePanel()` 先清旧态（幂等）。
2. 用节点已有数据**立刻**填头部（type 徽章 / 星系名+色 / 标题 / 钩子）与**邻居列表**
   （`adj[id]` 按 `weight` 降序；每项 = 星系色点 + `alias || 截断标题` + 相似度；点击 → `openPanel(邻居id)`）。
3. `fetch('/api/item/' + encodeURIComponent(id))` 填**摘要/作者/关键词/笔记**；
   失败或 404 时这几项显示占位（"—"），**不阻塞**头部与邻居（侧栏始终可用）。
4. **联动星图**：选中 + 邻居 `opacity 1`，其余 `0.12`（含其 label）；`controls.autoRotate = false`。
5. 底部链接 = `(type==='video' ? '/videos/' : '/blogs/') + encodeURIComponent(id)`。
6. 显示 `#nodePanel`。

**`closePanel()`**（幂等）：隐藏 `#nodePanel`；`restoreAll()` 还原全部节点透明度/可见性/label；
仅当 `currentMode == null` 时 `controls.autoRotate = true`（不跟激活模式抢）。

**触发改写**：现有 rest 态 canvas `click`（原 `window.open(...)`）改为：
```
if (currentMode === 'path') return;     // path 选星独占（不变）
if (currentMode) return;                // 其它动词模式下不开侧栏
if (hovered) openPanel(hovered.userData.id);
else closePanel();                      // 点空白 → 关闭
```

**关闭途径**：✕ 的 click；`document` 上的 `keydown` Esc；上面"点空白关闭"。

**与模式互斥**：`setMode()` 开头调用 `closePanel()`（开任一动词先收侧栏）。

**取舍**：邻居用可见边集（与图上一致）；联动变暗复用既有 `restoreAll()` 与 path/tour 同款透明度手法；
侧栏宽度/配色沿用暗色主题；无新第三方依赖。

## 测试

沿用 `tests/unit/` + TestClient，网络无关。

- **`GET /api/item/{id}` 路由**（可自动化）：
  1. 已知 id → 200，载荷含 `id/type/title/author/published_at/summary/keywords/note_html`。
  2. 未知 id → 404。
  3. 先写一条 markdown 笔记 → `note_html` 含渲染后的 HTML（如 `<strong>`/`<p>`）。
  4. 无笔记 → `note_html == ""`。
  5. `safe_id` 行为：带路径分隔符/越界的 id 不命中（404，不触达文件系统外）。
- **`_item_detail` helper**（若独立可测）：给定 item + note 串，返回正确 dict 形状。
- **前端侧栏交互**（open/close/邻居跳转/Esc/空白关闭/联动变暗/模式互斥）：**无自动化测试** ——
  与现有 `graph.html` 纯手验 JS 一致；靠 `node --check` + jinja parse + 浏览器实测（Playwright 驱动）验收。

## 不做（YAGNI）

- 移动端/窄屏适配（个人本地桌面应用）。
- 聚焦镜头移动（已选"高亮+变暗+暂停自转"，镜头不动）。
- 邻居 mini-graph（用列表即可）。
- 在侧栏内编辑笔记（只读展示；编辑仍在详情页）。
- 把 `/api/graph` 载荷加重塞详情（按需拉取更省）。

## 受影响文件一览

- 改 `src/aishelf/site/app.py`：`GET /api/item/{id}` 路由 + `_item_detail` helper。
- 改 `src/aishelf/site/templates/graph.html`：`#nodePanel` DOM + CSS + `openPanel`/`closePanel` +
  click 改写 + Esc 监听 + `setMode` 关闭钩子。
- 新增 `tests/unit/test_site_item_route.py`（或并入 `test_site_app.py`）：路由测试。
- 改 `CLAUDE.md`：记录 `/api/item/{id}` 与 `/graph` 的节点侧栏。

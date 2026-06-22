# 语义孤岛/孤本 (Islands) — 设计

- 日期：2026-06-22
- 状态：已批准，待写实现计划
- 主题：`GET /islands` 语义孤岛/孤本

## 目标

一个 `GET /islands` 页面，从已有的 `edges` 表（语义相似图）算出每条收藏的
"语义度数"，列出最孤立的收藏：

- **孤本（零连接）**：有 embedding 但在 `edges` 表里没有任何邻居（没有任何其它
  收藏与它的 cosine ≥ `GRAPH_SIM_FLOOR=0.5`）—— 语料里独一无二的内容。
- **弱连接（1–2 个邻居）**：度数很低、只跟极少数收藏相关。

**定位**：纯数据「distill 而非 decorate」，复用为 `/graph` 已经建好的 `edges`
表，回答一个真实的问题——"我收藏里哪些被冷落了 / 最独特？"。属于一个全新形态
（一个连接性诊断列表），区别于现有的 LLM-段落页和 timeline/keywords 这两个
纯数据视图。

**硬约束**：零 LLM、零新依赖、零 DB schema 改动、零新配置、零持久化。符合
`简洁 + 实用 + 好玩，拒绝花里胡哨`。

## 关键概念

`edges` 表（`src TEXT, dst TEXT, weight REAL, PRIMARY KEY(src,dst)`，无向、
canonical `src < dst`）存的是**完整阈值图**：每对 cosine ≥ 0.5 的收藏存一条。
因此一个 id 在 `edges` 里的**度数 = 与它语义相近的收藏数**。

- **只分析有 embedding 的收藏**（`items.embedding IS NOT NULL`）。没有 embedding
  的项天然没有边，但那是"未知"，不是"语义孤岛"——必须排除，否则未配 embedding
  时所有项都会被误判为孤本。
- `edges` 的端点必然都是有 embedding 的项（边只在已嵌入项之间生成）。

## 数据源

读 **derived SQLite DB**（与 `/graph`、`/timeline` 同源；contract 文件仍是
source of truth，DB 可重建）。需要的表/列全部已存在，无迁移：

- `items`：`id, type, title, hook`，过滤 `embedding IS NOT NULL`
- `edges`：`src, dst`

## 模块：`src/aishelf/site/islands.py`

镜像 `timeline.py` 的 **pure + 容错 IO** 拆分。

### `build_islands(items, edges, *, max_weak_degree=2) -> dict`（纯函数）

输入：
- `items`：`[{id, type, title, hook}, ...]` —— 仅有 embedding 的项。
- `edges`：`[(src, dst), ...]`（或等价的可迭代对）。
- `max_weak_degree`：弱连接上界（默认常量 `WEAK_MAX_DEGREE = 2`）。

处理：
1. 用 `items` 建 `by_id = {id: item}`。只统计端点都在 `by_id` 里的边（防御性
   跳过引用到已删项的脏边）。
2. 每个 id 的度数 = 关联边数；邻居集 = 对端 id 集合（无向，两个方向都算）。
   `by_id` 里没有出现在任何边里的 id 度数为 0。
3. `lone`：度数 0 的项，按 `title` 升序（确定性）。每条
   `{id, type, title, hook}`（`hook` 为 None → `""`）。
4. `weak`：`1 <= 度数 <= max_weak_degree` 的项，按 `(degree, title)` 升序。每条
   `{id, type, title, hook, neighbors}`，其中 `neighbors` 为
   `[{id, type, title}, ...]`（用 `by_id` 解析；解析不到的邻居跳过），按邻居
   `title` 升序。
5. `stats`：`{"embedded": len(items), "lone": len(lone), "weak": len(weak),
   "connected": embedded - lone - weak}`。

输出：`{"lone": [...], "weak": [...], "stats": {...}}`。`items` 为空 →
`{"lone": [], "weak": [], "stats": {"embedded": 0, "lone": 0, "weak": 0,
"connected": 0}}`。

纯函数：不读文件/DB、不调 LLM。

### `load_islands(db_path) -> dict`（容错 IO）

读 `items`（`id, type, title, hook` where `embedding IS NOT NULL`）与
`edges`（`src, dst`），组装并调用 `build_islands`，返回其结果。

容错：DB 缺失、表/列不存在（旧版）→ 捕获 `sqlite3.Error`，返回
`build_islands([], [])` 的空结果，**绝不抛**（与 `timeline.load_timeline` /
`learn.load_galaxies` 一致）。

## 路由：`GET /islands`

在 `app.py` 注册（在只读页面路由群里）。调用
`islands.load_islands(default_db_path(get_data_dir()))`，结果传给
`islands.html`。只读、无副作用、无 passcode 门。

## 模板：`templates/islands.html`

- 继承 base；topbar（`templates/_topbar.html` 的 `<nav>`）加
  `<a href="/islands">孤岛</a>`。
- 顶部统计行：`已嵌入 N 条 · 孤本 X · 弱连接 Y`。
- **孤本（零连接）** 段：每行简单标记 + 标题链接（`/videos|blogs/{id}` 按
  `type`）+ 钩子（有则显示）。
- **弱连接（1–2 邻居）** 段：每行同上，附 `邻居：<链接>, <链接>`（邻居也链到
  其详情页）。
- 降级/空态：
  - `stats.embedded == 0` → 提示："语义孤岛需要先配置 `ATLAS_EMBED_*` 并运行
    `python -m aishelf.db sync --rebuild` 后才能分析。"
  - `embedded > 0` 且 `lone`、`weak` 均空 → "你的收藏彼此连接紧密，没有孤岛 🎉"。
- 模板 autoescape；标题/钩子转义；链接走现有路由约定。

## 错误处理与降级

- 无 DB / 旧 DB → `load_islands` 返回空 → 渲染 `embedded==0` 提示态，HTTP 200。
- 未配 embedding（edges 空、embedded 0）→ 提示态。
- 邻居 id 解析不到 → 跳过该邻居，不报错。

## 测试

`tests/unit/test_site_islands.py`：
- `build_islands`：
  - 度数与邻居计算（无向、两方向）。
  - `lone` = 度数 0，按标题排序。
  - `weak` = 1..max，按 `(degree, title)` 排序；邻居列表解析 + 邻居按标题排序。
  - `max_weak_degree` 边界（度数 == max 算弱，> max 算 connected）。
  - 脏边（端点不在 items）被跳过。
  - `hook=None` → `""`。
  - `stats` 各计数正确（含 connected）。
  - 空输入 → 空结构。
- `load_islands`：
  - 正常 DB（含 embedding 的项 + edges）→ 与直接喂 builder 一致。
  - 只读有 embedding 的项（无 embedding 的项被排除）。
  - DB 缺失 / 旧版缺列 → 空结果，不抛。

`tests/unit/test_site_islands_route.py`（TestClient，自建临时 DB，先
`Path(db).unlink(missing_ok=True)` 忽略 fixtures 里可能拷来的旧 DB）：
- populated → 200，含「孤本」段、孤本标题、弱连接邻居链接。
- 无 embedding（空/无 DB 的 data dir）→ 200，含配置提示文案。
- topbar 含 `href="/islands"`。

测试遵循现有约定：网络永远 mock；DB 用临时文件 + `db.schema` 直接建表灌数据
（embedding 列写一个非空 BLOB 占位即可，builder/loader 不解析其内容）。

## 非目标（YAGNI）

- 不加星系色点（孤岛关乎*连接*，非主题）；用简单中性标记。
- 不分页、不加筛选/排序控件（语料小，列全部）。
- 不展示 cosine 权重数值（只展示邻居身份）。
- 不引入新配置/新 DB 列/新依赖/LLM/持久化/缓存。
- 不改 contract、loader、sync、graph 逻辑。

## 文件清单

- 新增 `src/aishelf/site/islands.py`（`build_islands` + `load_islands` +
  `WEAK_MAX_DEGREE`）。
- 新增 `src/aishelf/site/templates/islands.html`。
- 改 `src/aishelf/site/app.py`（import `islands`；注册 `GET /islands`）。
- 改 `src/aishelf/site/templates/_topbar.html`（加「孤岛」链接）。
- 改 `src/aishelf/site/static/style.css`（`.islands` 样式）。
- 新增 `tests/unit/test_site_islands.py` + `tests/unit/test_site_islands_route.py`。
- 改 `CLAUDE.md`（描述新路由 / 新模块）。

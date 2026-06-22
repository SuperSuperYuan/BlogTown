# 收藏编年史 (Timeline) — 设计

- 日期：2026-06-22
- 状态：已批准，待写实现计划
- 主题：`GET /timeline` 收藏编年史

## 目标

一个 `GET /timeline` 页面，把全部收藏（视频 + 博客）按 `collected_at`
倒序、按月分组排成一条垂直时间线；每条携带其所属主题星系的色点、标题链接、
以及 A 钩子（「为什么值得看」）。顶部一行统计概览，底部星系色图例。

**定位**：纯数据的「distill 而非 decorate」——把扁平 browse 列表里看不见的
*时间结构* 提炼出来，让用户一眼看见自己兴趣随时间的迁移。属于一个全新形态
（区别于现有的 collide/mirror/learn/critique/ask 这类 stream-an-LLM-段落页，
以及 keywords/graph 这两个已有的纯数据视图）。

**硬约束**：零 LLM 调用、零新依赖、零 DB schema 改动、零新配置。符合
`简洁 + 实用 + 好玩，拒绝花里胡哨` 原则（好玩来自内容惊喜：看见自己的收藏轨迹）。

## 数据源

读 **derived SQLite DB**（与 `/graph` 的 `load_graph` 同样的做法：分析/派生视图
天然以 DB 为源；contract 文件仍是 source of truth，DB 可随时由
`python -m aishelf.db sync` 重建）。

需要的列全部已存在，无需迁移：

- `items` 表：`id, type, title, collected_at, cluster, hook`
- `clusters` 表：`id, name, color`

当 `ATLAS_EMBED_*` 未配置时，`cluster` 全为 `NULL`、`clusters` 表为空 —— 时间线
仍然工作（`collected_at` 为 `NOT NULL`，永远存在；`hook` 可能为空），此时所有点
归「未归类」灰点。

## 模块：`src/aishelf/site/timeline.py`

镜像 `digest.py` / `learn.py` / `mirror.py` 的 **pure + 容错 IO** 拆分。

### `build_timeline(items, clusters_by_id) -> dict`（纯函数）

输入：
- `items`：`[{id, type, title, collected_at, cluster, hook}, ...]`（来自 DB 行；
  `cluster` 可能为 `None`，`hook` 可能为 `None`/空）。
- `clusters_by_id`：`{cluster_id: {"name": str, "color": str}}`。

处理：
1. 按 `collected_at` **倒序**排序（最新在前）。`collected_at` 是 ISO 字符串，
   字符串倒序即时间倒序。
2. 分月桶：月 key 由 `collected_at` 前缀（`YYYY-MM`）得出，桶标题渲染为
   `2026年6月`（去掉前导零）。月桶按时间倒序排列；桶内条目保持上面的倒序。
3. 每个条目映射为
   `{id, type, title, hook, cluster_name, cluster_color}`：
   - `cluster` 命中 `clusters_by_id` → 取其 `name`/`color`。
   - `cluster` 为 `None` 或未命中 → `cluster_name="未归类"`、
     `cluster_color=UNCLASSIFIED_COLOR`（一个中性灰，如 `#888888`）。
   - `hook` 为 `None` → 渲染为空串（模板里不显示钩子行）。
4. 统计 `stats`：
   - `total`：条目总数。
   - `span`：最早月–最新月，如 `2026年4月 – 2026年6月`；只有一个月时只显示该月；
     `total==0` 时为空串。
   - `top_galaxy`：`{name, color, count}` —— 条数最多的星系（排除「未归类」；
     若只有未归类或为空则为 `None`）。
5. `legend`：本次出现过的星系列表 `[{name, color}, ...]`，按条数降序；
   「未归类」若出现则置于末尾。

输出：`{"months": [{"title": "2026年6月", "count": 12, "items": [...]}, ...],
"stats": {...}, "legend": [...]}`。`items` 为空时返回
`{"months": [], "stats": {"total": 0, "span": "", "top_galaxy": None},
"legend": []}`。

纯函数：不读文件、不连 DB、不调 LLM，便于单测。

### `load_timeline(db_path) -> dict`（容错 IO）

读 `items`（`id, type, title, collected_at, cluster, hook`）与 `clusters`
（`id, name, color`），组装成 `build_timeline` 的入参并调用它，返回其结果。

容错：DB 文件缺失、表不存在、或为旧版缺列 → 捕获并返回
`build_timeline([], {})` 的空结果（友好空状态），**绝不抛异常**
（与 `mirror.load_profile` / `learn.load_galaxies` 一致）。

## 路由：`GET /timeline`

在 `app.py` 注册。调用 `timeline.load_timeline(db_path)`（`db_path` 用现有
helper 取，与 `/graph` 等一致），把结果传给 `templates/timeline.html` 渲染。
只读、无副作用、无 passcode 门（与 browse/keywords/graph 同级）。

## 模板：`templates/timeline.html`

- 继承现有 base，topbar 增加「编年史」入口（在 `templates/_topbar.html` 的
  `<nav>` 链接列表里加一条 `<a href="/timeline">编年史</a>`）。
- 顶部一行统计：`共 N 条 · 跨度 {span} · 最活跃 {top_galaxy.name}`（带色点）；
  `total==0` 时不显示统计、改显示空状态。
- 主体：按月分组的垂直时间线 —— 每个月一个分隔标题
  `── 2026年6月 (12) ──`；其下每条收藏一行：星系色点（`cluster_color`）+
  标题（链到 `/videos/{id}` 或 `/blogs/{id}`，按 `type`）+ 钩子（有则显示，
  小字、次要色）。复用现有 browse 列表的视觉语汇，保持 简洁。
- 底部星系色图例：色点 + 名称，逐个列出 `legend`。
- 空状态：`还没有收藏` + 指向 `/collect` 的引导链接。
- 模板 autoescape；链接用现有 `safe_url`/路由约定，标题文本转义。

## 错误处理与降级

- 无 DB / 旧 DB → `load_timeline` 返回空 → 页面渲染空状态，HTTP 200。
- 未配 embedding（无星系）→ 所有点「未归类」灰，时间线照常；图例只有「未归类」
  或为空。
- 任何单条缺 `hook` → 该行不显示钩子，不报错。

## 测试

`tests/unit/test_site_timeline.py`（或并入既有 site 测试文件，遵循现有约定）：

- `build_timeline`：
  - 分月正确（同月归一桶，跨月分桶，桶按时间倒序）。
  - 桶内倒序（最新在前）。
  - 统计：`total` / `span`（多月、单月、空）/ `top_galaxy`（排除未归类、平局取最多）。
  - `cluster=None` 或未命中 → 「未归类」灰点。
  - `hook=None` → 空串、不崩。
  - `legend` 顺序（按条数降序、未归类置末）。
  - 空输入 → 空结果结构。
- `load_timeline`：
  - 正常 DB → 与直接喂行给 `build_timeline` 一致。
  - DB 文件不存在 / 表缺失 → 返回空结果，不抛。
- 路由 smoke（TestClient）：
  - `GET /timeline` 返回 200，含某月分隔标题或空状态文案。
  - topbar「编年史」链接存在。

测试遵循现有约定：网络永远 mock；DB 用临时文件 + `db.sync` 或直接建表灌数据。

## 非目标（YAGNI）

- 首版不加 type 过滤 / 关键词筛选 / 交互控件 —— 保持纯倒序时间线、简洁。
- 不做月度密度柱状图（已在选型中淘汰）。
- 不缓存、不持久化、不引入新配置 / 新 DB 列 / 新依赖 / LLM 调用。
- 不改 contract、loader、sync 逻辑。

## 文件清单

- 新增 `src/aishelf/site/timeline.py`（`build_timeline` + `load_timeline`）。
- 新增 `src/aishelf/site/templates/timeline.html`。
- 改 `src/aishelf/site/app.py`（注册 `GET /timeline`）。
- 改 `src/aishelf/site/templates/_topbar.html`（加「编年史」链接）。
- 新增 `tests/unit/test_site_timeline.py`。
- 改 `CLAUDE.md` 文档（描述新路由 / 新模块）。

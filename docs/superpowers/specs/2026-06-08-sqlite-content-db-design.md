# SQLite 派生数据库（结构化内容索引 + 全文检索）设计

**目标:** 在现有「Hermes 采集 → JSON 文件」之外，把采集到的内容**派生**进一个本地 SQLite 数据库，作为后续「消费功能」的基础。首个消费场景是**全文检索**（含中文），并为后续语义/向量检索预留扩展位。

## 背景与定位

现有架构里，Hermes（外部 agent）直接把记录**按 id 幂等**写入 `data/{videos,blogs}/<id>.json`；Atlas 站点只**按请求读取**这些文件（`contract.loader.load_items`）。站点对 Hermes 的写入时刻没有任何 hook —— 文件写发生在应用之外。

因此 DB 不可能在「采集那一刻」由站点顺手写入，只能由 Atlas 侧的一个**同步步骤**读取契约文件后填充。

**关键定位（已与用户确认）:**

- **DB 是文件的派生视图。** JSON 文件仍是唯一真相，Hermes 契约不变；SQLite 随时可从文件全量重建，丢失无所谓。
- **现有浏览/搜索路由完全不动**（仍读文件）。DB 只服务新增的消费功能。
- **核心消费场景 = 全文检索。** schema 聚焦单内容表 + 一张 FTS5 全文表；不引入 ORM/迁移框架，不做向量（留扩展位）。

## 承重假设（已验证）

- 本机 Python 自带 SQLite 3.51.2，FTS5 与 `trigram`/`unicode61` tokenizer 均可用。
- `trigram` 对中文 2 字词（如「检索」「模型」）匹配不到（需 ≥3 字），**不适用中文**。
- **bigram 预分词**方案（中文切 2-gram、ASCII 整词小写，用 `unicode61` 索引；查询同样 bigram 化）已验证可正确命中 2 字/多字 CJK 词、ASCII 词、大小写，且**无需任何额外依赖**。

## 架构与模块边界

新增子包 `aishelf/db/`，与 `contract`、`site` 平级。分层依赖单向：`site → db → contract`；`db` 只依赖 `contract` + 标准库。

```
aishelf/db/
  __init__.py
  config.py     # default_db_path(data_dir) -> <data_dir>/atlas.db；读 AISHELF_DB_PATH 覆盖
  schema.py     # DDL 常量 + connect()(WAL/row_factory/PRAGMA) + init_db()
  tokenize.py   # 纯函数 bigrams(text) + to_match_query(user_q)
  sync.py       # sync(data_dir, db_path) -> SyncSummary（全量扫描 + upsert + prune）
  search.py     # search(db_path, q, *, type=None, limit, offset) -> list[SearchHit]
  __main__.py   # CLI: python -m aishelf.db sync [--rebuild]
```

- **DB 文件:** 默认 `<data_dir>/atlas.db`（`data/` 已 gitignore → DB 不入库，符合「可重建」定位）。新增环境变量 `AISHELF_DB_PATH` 覆盖路径。
- DB 路径解析放在 `aishelf/db/config.py`，保持 `db` 不反向依赖 `site`。

## 组件

### 1. Schema（`schema.py`）

一张主表（契约是 `type` 判别联合，modality 专属字段设为可空列），一张独立 FTS5 虚拟表：

```sql
CREATE TABLE IF NOT EXISTS items (
  id            TEXT PRIMARY KEY,
  type          TEXT NOT NULL,
  title         TEXT NOT NULL,
  author        TEXT NOT NULL,
  author_id     TEXT,
  platform      TEXT NOT NULL,
  source_url    TEXT NOT NULL,
  published_at  TEXT NOT NULL,
  collected_at  TEXT NOT NULL,
  summary       TEXT NOT NULL,
  keywords      TEXT NOT NULL,        -- JSON 数组原样存
  thumbnail_url     TEXT,             -- video-only
  duration_seconds  INTEGER,          -- video-only
  embed_url         TEXT,             -- video-only
  cover_image_url   TEXT,             -- blog-only
  site_name         TEXT,             -- blog-only
  content_hash  TEXT NOT NULL,        -- sha1(规范化 JSON)，增量跳过用
  synced_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_type      ON items(type);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  item_id UNINDEXED,
  title, summary, keywords, author,
  tokenize='unicode61'                -- 存 bigram 化后的文本
);
```

- `items_fts` 存的是 **bigram 分词后**的文本，由 `sync` 在 Python 侧维护（**不用触发器**——因为分词必须在 Python 做）。`item_id` 为 `UNINDEXED` 列，用于回映射到 `items`。
- `connect()` 打开 WAL 模式 + `busy_timeout`，`row_factory = sqlite3.Row`。`init_db()` 幂等建表/建 FTS。

### 2. 分词（`tokenize.py`，纯函数）

- `bigrams(text) -> str`：用正则切出 `[A-Za-z0-9]+`（小写整词保留）与 CJK 连续段（切 2-gram；单字时保留单字），空格连接。
- `to_match_query(user_q) -> str`：对查询做同样 bigram 化，各 bigram 加双引号并以 ` AND ` 连接，构成 FTS5 `MATCH` 表达式；空/纯符号查询 → 返回空串（调用方据此返回 `[]`）。
- bigram 只保留字母数字 + CJK，天然剥离 FTS 特殊字符 → 注入安全。

### 3. 同步（`sync.py`）

`sync(data_dir, db_path) -> SyncSummary`，全程单事务（原子，类比项目的原子文件写）：

```
items = load_items(data_dir)          # 复用契约 loader：已验证、坏记录自动跳过
con = connect(db_path); init_db(con)
BEGIN
  seen = set()
  for it in items:
    h = sha1(规范化 JSON)
    若 items 已有该 id 且 content_hash == h → unchanged，跳过
    否则 upsert items 行（INSERT ... ON CONFLICT(id) DO UPDATE）
         删除并重插该 id 的 items_fts 行（bigram 化 title/summary/keywords/author）
    seen.add(it.id)
  prune：删除 items / items_fts 中 id ∉ seen 的行    # 文件被删 → DB 同步删
COMMIT
return SyncSummary(added, updated, removed, unchanged)
```

- 幂等、可全量重建；文件删除会传导到 DB（站点 `delete_item` 删文件后，下次 sync 自动清 DB 行）。
- 语料只有几十条，全量扫描成本可忽略；`content_hash` 仅用于跳过未变记录的 FTS 重写与 summary 报告。

### 4. 触发时机（每次采集后）

- **定时采集:** `scheduler` 里 `collect.run_once(...)` 返回后调用 `db.sync.sync(...)`；记录 summary；失败仅日志、不影响调度。
- **手动 chat 采集:** `/collect/chat` 是流式 SSE。包一层生成器，在 `done` 事件后（`finally`）起一个**后台线程**跑 sync —— 不阻塞响应。（Hermes 的文件写是本轮 tool 调用，`done` 时已落盘。）
- **手动兜底/初始回填:** `python -m aishelf.db sync`（`--rebuild` 先 drop 再建）。这是把现有文件灌进 DB、以及 DB 丢失后恢复的入口。

> **权衡（明确记录）:** 用户未选「启动时同步」与「定期同步」。意味着若 DB 被删且之后没有新采集，检索会落后于文件，直到手动 `sync`。首次部署需手动跑一次 `python -m aishelf.db sync` 回填现有文件。

### 5. 检索接口（`search.py`）

```python
search(db_path, q, *, type=None, limit=20, offset=0) -> list[SearchHit]
```

- 经 `to_match_query` 把 `q` bigram 化 → 构造 FTS5 `MATCH`，`bm25()` 排序。
- 跨 title/summary/keywords/author 命中；可选 `type` 过滤（video/blog）；分页。
- 命中后回 `items` 表取完整结构化字段，返回 `SearchHit`（结构化字段 + 可选 snippet）。
- 空查询/无效字符 → 返回 `[]`。

### 6. HTTP 端点（首个消费功能雏形）

- 新增只读 `GET /api/search?q=&type=&page=` JSON 路由：**开放访问**（只读、不触碰 Hermes 预算，不走采集口令），调用 `db.search.search(...)`，返回 JSON。
- **现有 `/search` 页面与浏览路由完全不动**（仍读文件）。
- 路由从 `app.py` 调 `db.search` + `db.config.default_db_path(get_data_dir())`。

### 7. 配置与文档

- 新增环境变量 `AISHELF_DB_PATH`（默认 `<data_dir>/atlas.db`）。
- 更新 `CLAUDE.md`：模块清单加 `aishelf/db/`；Config 段加 `AISHELF_DB_PATH`；Commands 段加 `python -m aishelf.db sync`。

## 错误处理

- **sync 失败:** 日志记录、不抛给调用方（调度器/路由）；DB 是派生的，下次采集或 CLI 重跑即恢复。
- **DB 锁:** WAL 模式 + `busy_timeout`，缓解后台 sync 线程与读查询竞争。
- **坏记录:** 已由契约 loader 跳过，不进 DB。
- **FTS 特殊字符:** bigram 化已剥离，查询安全。

## 测试（全部离线，DB 用 `tmp_path`）

- `tokenize`：CJK 1/2/多字、ASCII、混排、标点、大小写。
- `to_match_query`：表达式构造 + 空查询。
- `sync`：fixture JSON → sync → 校验行；改/删文件再 sync → 校验 upsert/prune；未变记录走 hash 跳过；prune 删除传导。
- `search`：种子 DB → CJK 2 字/多字/ASCII 查询、`type` 过滤、bm25 排序、空查询、无命中、分页。
- `/api/search` 路由：`TestClient`（不连网）冒烟。
- 复用 `tests/fixtures/contract/`；触发器调用可 mock `sync` 断言被调。

## 不做（YAGNI / 显式划界）

- 不做向量/语义检索（仅预留 `items` + 独立 FTS 的可扩展结构）。
- 不做 keywords 独立维表/统计聚合（当前消费场景只有检索）。
- 不把 notes 纳入 DB。
- 不改现有文件读路径（浏览/搜索/详情/作者页）。
- 不引入 ORM、迁移框架、startup/periodic 同步。

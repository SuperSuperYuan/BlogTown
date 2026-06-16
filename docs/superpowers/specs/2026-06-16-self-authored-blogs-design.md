# 自写 Markdown 博客 — 设计

## 概览

为 Atlas 增加一个**自己写博客**的能力:用 markdown 写文章,文章正文存在本地、
详情页内联渲染,并**合并进现有 `/blogs` 列表**,以一个「原创」徽章与 Hermes
采集来的条目作视觉区分。采集条目的卡片格式、详情页、存储格式**完全不变**。

与现状的关键差异:今天的博客是**采集来的元数据 + 外链** —— 详情页显示摘要和
「阅读全文(原站)」按钮,指向外部 `source_url`,本地不存正文、全站没有任何
markdown 渲染。本特性新增的是**由用户撰写、正文存在本地并内联渲染**的博客。

## 已确定的需求

- **展示位置**:合并进 `/blogs` 列表,自写文章带「原创」视觉标记;采集卡片格式不变。
- **编辑字段(极简)**:只填**标题 + markdown 正文**。作者取配置默认值,摘要从正文
  自动截取,关键词留空,发布时间 = 当下。
- **发布后管理**:可重新编辑、可删除;**无草稿**状态(点发布即上线)。
- **访问控制**:**开放**,不挂口令门(与现有的笔记/删除一致;写博客不花外部预算)。

## 架构方案与取舍

**方案 A(采用)— 复用 `BlogItem` + `data/blogs/`,加 `body` 与 `origin` 字段。**
自写文章就是一条普通的 `BlogItem` JSON,写进 `data/blogs/<id>.json`,只多了
`body`(markdown 原文)和 `origin: "self"`。它自动流经现有的 loader → `/blogs`
列表、DB sync → 搜索/问答/图谱、删除 —— 全部复用。详情页按 `origin` 分支渲染。
- 优点:复用最大化,新增代码最少,自动进列表 + 搜索 + 图谱。
- 代价:给 Hermes「拥有」的契约加了字段 —— 但 Hermes 忽略额外字段
  (`extra="ignore"`),两个字段都可空且有默认值,对现存记录零影响。

**方案 B(否决)— 独立存储 `data/posts/` + 新模型 `PostItem`。** 契约更纯净,但
loader / sync / search / graph / 列表合并处处要特判或重写,与「合并进 /blogs」的
目标冲突,重复劳动不值。

**方案 C(否决)— 直接存 `.md` + YAML front-matter。** git 友好但完全绕开现有
JSON 契约管线,DB sync / loader 都得改,对本地个人应用过度设计。

## 组件设计

### 1. 数据模型(`contract/models.py`)

给 `BlogItem` 增加两个字段:

```python
class BlogItem(ContentItem):
    type: Literal["blog"] = "blog"
    cover_image_url: str | None = None
    site_name: str | None = None
    author_id: str | None = None
    body: str | None = None                       # markdown 原文,仅自写文章有
    origin: Literal["collected", "self"] = "collected"
```

- 采集记录不带这两个字段 → 解析后 `body=None`、`origin="collected"`,行为不变。
- `extra="ignore"` 保证向后兼容,旧 JSON 文件无需迁移。

### 2. 写入与持久化(新模块 `site/posts.py`)

复用 `notes.py` 的原子写模式(唯一 `.tmp` + `os.replace`)与 `items.safe_id`。

- `create_post(title, body) -> BlogItem`:
  - `id` = `post-<sha1(title + iso_timestamp)[:12]>`,经 `safe_id` 校验
    (字符集 `[A-Za-z0-9._-]`,前缀 `post-` 满足)。
  - `author` = 配置默认值(见配置节)。
  - `summary` = 从 `body` 自动截取:剥离常见 markdown 标记后取前 ~120 字。
  - `keywords = []`,`platform = "atlas"`,`source_url = ""`(自写无外链)。
  - `published_at` / `collected_at` = 当下 ISO 时间。
  - `origin = "self"`,`body` = 原文。
  - 原子写到 `data/blogs/<id>.json`。
- `update_post(id, title, body) -> BlogItem`:读回记录,更新 `title` / `body` /
  `summary`,**保留原 `published_at`**,原子覆盖写。仅允许 `origin=="self"` 的记录。
- 写入/更新后**off-thread 触发 `python -m aishelf.db sync`**(与保存笔记同样的
  机制),使新文章立刻可搜索、进图谱。
- 删除:直接复用现有 `items.delete_item` 与 `POST /delete/{id}`,无需新代码。

### 3. Markdown 渲染(新模块 `site/markdown.py`)

`render_markdown(text: str) -> str`:渲染 markdown → HTML 并**消毒**。

- 推荐依赖:`markdown-it-py`(渲染)+ `nh3`(HTML 消毒,Rust 实现、快)。
- 输出在模板中经 `| safe` 注入(已消毒)。
- 作者是唯一可信的本地用户,消毒属廉价的纵深防御:剥离 `<script>`、内联事件
  处理器、`javascript:` URL 等。
- 渲染异常兜底为转义后的纯文本,绝不抛出导致页面崩溃。

### 4. 路由(`site/app.py`)

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/write` | 新建编辑页 |
| GET | `/write/{id}` | 编辑已有自写文章;非自写或不存在 → 404 |
| POST | `/posts` | 新建 → 成功后 302 到 `/blogs/{id}` |
| POST | `/posts/{id}` | 更新 → 成功后 302 到 `/blogs/{id}` |
| POST | `/posts/preview` | 返回 `render_markdown(body)` 的消毒 HTML,供实时预览 |

- 全部**开放访问**,不经 `_require_collect_token`。

### 5. 模板

- `base.html`:顶栏增加「写博客」链接 → `/write`。
- 新模板 `write.html`:标题输入框 + markdown 文本域 + 发布按钮,**左写右预览**
  两栏布局,沿用 `style.css`,风格简洁。
- `blog_detail.html`:按 `item.origin` 分支 —— `"self"` 时**内联渲染 `body`** +
  显示「原创」徽章 + 隐藏「阅读全文(原站)」按钮;否则**维持现状,字节不动**。
- `blogs.html` / 博客卡片:自写条目显示一个小「原创」徽章作视觉区分;采集卡片
  格式不变。

### 6. 实时预览的做法

编辑页文本域 `input` 事件**防抖**后 `fetch('/posts/preview')`,用**服务端同一个
`render_markdown`** 渲染右栏。这样:

- 预览与发布后输出**逐字节一致**(同一渲染器 + 同一消毒规则,无前后端差异)。
- 不引入客户端 markdown 库(沿用现有「必要时才上 CDN」的克制)。

## 数据流

```
写博客页 (/write)
   │ 标题 + markdown 正文
   ▼
POST /posts ──► posts.create_post() ──► 原子写 data/blogs/<id>.json
   │                                         │ (body + origin="self")
   │                                         ▼
   │                                  off-thread: db sync
   │                                  (索引 → 搜索/问答/图谱)
   ▼
302 → /blogs/<id> (blog_detail, origin==self → 内联渲染 markdown)

/blogs 列表 ──► 现有 loader 读 data/blogs/*.json ──► 自写与采集混排
                                                    (自写带「原创」徽章)
```

## 配置

- 新增 `ATLAS_BLOG_AUTHOR` —— 自写文章的默认作者名,默认值可取一个合理常量
  (如 `"我"`)。其余配置不变。

## 错误处理

- 空标题或空正文 → 表单返回校验错误,**不写盘**。
- `GET /write/{id}` / `POST /posts/{id}` 命中不存在或 `origin!="self"` 的 id → 404。
- markdown 渲染失败 → 兜底转义纯文本,页面不崩。
- 沿用全站约定:loader 对坏记录跳过并记日志,而非崩溃。

## 测试(`tests/unit/`)

- `posts.create_post` / `update_post`:字段正确性、原子写、`published_at` 在更新时
  保留、`summary` 自动截取、`safe_id` 边界。
- `markdown.render_markdown`:基本渲染正确;消毒生效(`<script>`、内联事件、
  `javascript:` URL 被剥离);异常兜底为转义文本。
- 详情页:`origin=="self"` 走内联渲染 + 徽章 + 无原站按钮;采集条目维持现状。
- 路由:`/write` 新建空表单、`/write/{id}` 预填、对非自写 id 返回 404;
  `/posts` 创建后重定向;`/posts/preview` 返回消毒 HTML。
- `/blogs` 列表:自写与采集条目混排,自写带徽章。
- 沿用现有 fixture 风格(`tests/fixtures/contract/`);网络/Hermes 一律 mock。

## 不做(YAGNI)

- 草稿状态。
- 图片上传(可在正文里用外链图片 URL)。
- 富文本/所见即所得编辑器。
- 写博客的口令门。
- 自写文章的独立列表页。

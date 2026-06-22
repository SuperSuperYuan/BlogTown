# 相关标签/共现 (Co-tags) — 设计

- 日期：2026-06-22
- 状态：已批准，待写实现计划
- 主题：`GET /keyword/{kw}` 页的「常一起出现」标签块

## 目标

在标签页 `GET /keyword/{kw}`（列出携带某关键词的全部收藏）顶部加一行
**「常一起出现」**：统计**当前匹配的那批收藏**里，除聚焦词 `kw` 外哪些关键词
共现最多，按次数降序，每个 chip 链到 `/keyword/{other}`，丰富标签导航。

**定位**：纯数据「distill」，复用已有标签基础设施（`views.by_keyword` /
`views.keyword_counts`）。一个标签导航的小增强，而非新页面——刻意求变，避免
又一个独立列表页。

**硬约束**：零 LLM、零新依赖、零新配置、零 DB 改动、**不新建模块**（逻辑进
已有 `views.py`）。符合 `简洁 + 实用 + 好玩，拒绝花里胡哨`。

## 数据源

读 `data/` 文件（per-request），与标签页现有路径一致：路由已有
`mine = views.by_keyword(_items(), kw)`（匹配 `kw` 的全部条目），共现统计直接在
这批上做。

## 纯函数：`views.co_keywords(items, kw, *, limit=12)`

放进 `src/aishelf/site/views.py`，紧邻 `keyword_counts`，复用其大小写/去重语义。

输入：
- `items`：**已携带 `kw`** 的 ContentItem 列表（路由传入的 `mine`）。
- `kw`：聚焦关键词（用于排除自身）。
- `limit`：返回上限（默认常量值 `12`）。

处理（镜像 `keyword_counts`）：
1. `needle = (kw or "").strip().lower()`。
2. 遍历 `items`；对每个 item 的 `keywords`，按 `k.strip().lower()` 归并，
   **每项内同一 key 只计一次**（用 per-item `seen` 集）。
3. 跳过空 key 和 `key == needle`（排除聚焦词本身）。
4. `counts[key] += 1`；`display.setdefault(key, k)`（首见原始大小写作展示）。
5. `pairs = [(display[k], counts[k]) ...]`，按 `(-count, display.lower())` 排序，
   取前 `limit`。

输出：`[(display, count), ...]`；无共现 → `[]`。纯函数：不读文件/DB、不调 LLM。

边界：
- `needle` 为空（理论上不会，路由 404 已挡空匹配）→ 仍安全：不排除任何词，
  正常统计（但调用方只在有匹配时调用）。
- 关键词中含与 `kw` 不同大小写的同词 → 归并到同一 key、被 `needle` 排除。

## 路由：`keyword_page`

在已有逻辑后加一行：

```python
mine = views.by_keyword(_items(), kw)
if not mine:
    raise HTTPException(status_code=404)
co_tags = views.co_keywords(mine, kw)
...
return templates.TemplateResponse(request, "keyword.html",
    {"kw": kw, "videos": vids, "blogs": blogs, "co_tags": co_tags})
```

（保留现有 `kw/videos/blogs` 上下文键，新增 `co_tags`。）

## 模板：`keyword.html`

在 `<h1>标签「{{ kw }}」</h1>` 下方插入：

```html
{% if co_tags %}
<p class="cotags">常一起出现：{% for k, c in co_tags %}<a href="/keyword/{{ k|urlencode }}">{{ k }}<span class="ct-count">{{ c }}</span></a>{% endfor %}</p>
{% endif %}
```

- 与标签云一致用 `|urlencode` 编码链接；文本 autoescape。
- 为空时整行不渲染。
- 小号 `.cotags` / `.ct-count` 样式（复用标签云配色思路）。

## 错误处理与降级

- 无共现关键词 → `co_tags == []` → 整行不渲染，页面照常。
- 关键词缺失/空列表的 item → `keyword_counts` 同款 `getattr(... or [])` 容错
  （此处 `items` 来自 by_keyword，均有 keywords）。

## 测试

`tests/unit/test_site_views.py`（`co_keywords` 与 `keyword_counts` 同处）：
- 基本共现计数 + 按 count 降序、平局按 display 升序。
- 排除聚焦词 `kw` 本身。
- 大小写归并：`RAG`/`rag` 计为一项，display 取首见大小写。
- 单项内同一关键词只计一次。
- `limit` 截断。
- 无共现（每个匹配项只有 `kw` 一个关键词）→ `[]`。

`tests/unit/test_site_keywords.py`（已有标签页 smoke 同处）：
- `/keyword/{kw}` 200，含「常一起出现」字样 + 某共现标签的 `/keyword/{other}` 链接。
- 一个不与任何其它标签共现的关键词页 → 不含「常一起出现」（可选，
  或断言该标签页仍 200）。

测试遵循现有约定：用 `tests/fixtures/contract` 夹具 + TestClient。

## 非目标（YAGNI）

- 不显示共现权重/百分比，只显示次数。
- 不分页、不加交互筛选。
- 不改标签云 `/keywords` 页。
- 不新建模块/配置/DB 列/依赖/LLM。

## 文件清单

- 改 `src/aishelf/site/views.py`（加 `co_keywords` + 常量 `CO_TAGS_LIMIT = 12`）。
- 改 `src/aishelf/site/app.py`（`keyword_page` 计算并传 `co_tags`）。
- 改 `src/aishelf/site/templates/keyword.html`（共现标签行）。
- 改 `src/aishelf/site/static/style.css`（`.cotags` 样式）。
- 改 `tests/unit/test_site_views.py` + `tests/unit/test_site_keywords.py`。
- 改 `CLAUDE.md`（描述共现块）。

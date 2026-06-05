# 定时任务前端（并入 Hermes 页面）设计

**目标:** 在现有的 Hermes 采集页 `/collect` 上加一块「定时采集」区域，可以**展示**当前定时计划列表（含上次运行时间），并**配置**它们（新增 / 编辑 / 启停 / 删除）—— 不新增独立页面。改动写回 `config/schedules.yaml`，与现有调度器共用同一份配置。

## 背景

定时采集后端已就绪（`schedules.load_schedules` / `due_schedules`、`scheduler.run_due_now`、`schedule_state`）。本功能加「写入能力 + 路由 + 在 `/collect` 页内的一块 UI」。`/collect` 页已经有「采集口令」输入框（存于 `localStorage["aishelf_collect_token"]`），定时任务的写操作直接复用它，无需再加口令输入。

## 鉴权（关键）

新建/修改定时任务 = 让 Hermes 反复花钱采集，比一次性采集更敏感。因此**所有写操作复用采集口令**（`X-Collect-Token` + 白名单），与 `/collect/chat` 同一把锁。展示（随 `GET /collect` 一起渲染）保持开放，与该页其余部分一致。这关闭了"局域网访客绕过口令排定期采集"的漏洞。

## 组件

### 1. 写入能力 `aishelf.site.schedules.save_schedules`

- `save_schedules(schedules, path=None)`：把 `Schedule` 列表序列化为
  `{"schedules": [{name, time:"HH:MM", prompt, enabled}, ...]}` 并**原子写**
  （`mkstemp` + `os.replace`）到配置路径（同 `load_schedules` 的路径解析）。
- 与 `load_schedules` round-trip 一致。

### 2. 鉴权助手 `app._require_collect_token`

- 抽出现有 `/collect/chat` 里的口令校验为一个函数：口令不在白名单 → 403
  （白名单为空时记一条管理员提示日志）。`/collect/chat` 与三个 schedule 写路由共用，DRY。

### 3. 路由（`app.py`）

- `GET /collect`（改）— 除聊天界面外，额外把 `schedules.load_schedules()` 与
  `schedule_state.load_state(data_dir)` 传进模板，用于渲染定时区域。**开放**。
- `POST /schedules`（**gated**）— 表单字段 `name` / `time` / `prompt` / `enabled`。校验：
  - `name` 经 `items.safe_id`（字母/数字/`.-_`），非法 → 400；
  - `time` 经 `schedules._parse_time`，非 `HH:MM` 或越界 → 400；
  - `prompt` 非空 → 否则 400。
  - **按 name upsert**（已存在则覆盖，兼作编辑），保存。
- `POST /schedules/{name}/toggle`（**gated**）— 翻转该条 `enabled`，保存；无此 name → 404。
- `POST /schedules/{name}/delete`（**gated**）— 删除该条，保存；无此 name → 404。
- 写路由成功返回 `{"ok": true}`（JSON）；前端成功后 `location.reload()`。

### 4. 前端（扩展 `templates/collect.html`，不新增页面）

- 在聊天 + actionbar 之下加一块 `<section class="schedules">`「定时采集」：
  - **列表**：表格列 = 时间 / 名称 / 采集需求 / 状态（启用·停用徽标）/ 上次运行 / 操作（启停、编辑、删除）。空态提示「暂无定时任务」。
  - **新增/编辑表单**：名称、时间（`<input type="time">`）、需求（textarea）、启用（checkbox）。提交即 upsert；点某条「编辑」把其值填入表单。
- 复用页面已有的 `localStorage["aishelf_collect_token"]` 作为 `X-Collect-Token`；写操作用 `fetch`。403 → 提示并高亮已有的口令框；成功 → `location.reload()`。
- 合理布局即可，沿用页面既有视觉风格；不改导航。

## 错误处理

- 校验失败 → 400 + 中文 message，前端在表单旁提示。
- 口令无效 → 403，前端提示并高亮口令框。
- 写文件失败 → 抛出（原子写保证不留半截文件）。

## 测试

- `save_schedules`：save→load round-trip；原子写不留 `.tmp`；写到 `AISHELF_SCHEDULES` 指定路径。
- `GET /collect`：仍渲染聊天（既有测试绿）；额外展示已有计划的 name/prompt 与定时区域标题；空目录显示空态且不报错。
- `POST /schedules`：无口令 → 403；有口令 → 新增并持久化；同名 → 覆盖（upsert）；坏 time → 400；坏 name → 400；空 prompt → 400。
- `POST /schedules/{name}/toggle`：有口令翻转 enabled 并持久化；无口令 → 403；未知 name → 404。
- `POST /schedules/{name}/delete`：有口令删除并持久化；无口令 → 403；未知 name → 404。
- 复用的 `_require_collect_token`：`/collect/chat` 既有测试仍绿（无回归）。

# 定时采集（in-process 调度）设计

**目标:** 让 Hermes 采集能按配置定时自动触发 —— 例如「每天 10:00 检查某博主是否有新视频，有则采集」。调度随站点进程运行，错过的当天任务在下次启动时补跑。

## 背景与关键简化

现有采集是交互式的：`/collect` 页面流式调用 Hermes，Hermes 自己爬取并把记录**按 id 幂等**写入 `data/{videos,blogs}/<id>.json`。

因此「有更新才采集」无需我们做差异检测：定时**重跑同一个采集 prompt** 即可 —— 新条目被追加，已存在的 id 覆盖（幂等）。本功能本质是「按计划重跑一个采集 prompt」，不是「构建更新检测器」。

## 组件

### 1. 调度配置 `config/schedules.yaml`

- **gitignore**；附committed模板 `config/schedules.example.yaml`。
- 路径可用环境变量 `AISHELF_SCHEDULES` 覆盖；默认 `<repo>/config/schedules.yaml`。
- 结构：
  ```yaml
  schedules:
    - name: karpathy-daily        # 唯一标识，兼作状态记录 key
      time: "10:00"               # 每天本地时间 HH:MM
      prompt: "检查 Andrej Karpathy 的 YouTube 最近视频，有新的就采集"
      enabled: true               # 省略默认 true
  ```
- v1 仅支持「每天 HH:MM」。

### 2. 调度核心 `aishelf.site.schedules`

- `Schedule` 数据类：`name: str`、`hour: int`、`minute: int`、`prompt: str`、`enabled: bool`。
- `load_schedules(path=None) -> list[Schedule]`：读 YAML，逐条校验，**跳过并记录**坏条目（缺 name/prompt、time 非 `HH:MM`、name 重复取第一条）。文件缺失/为空/读不了 → 返回 `[]`。路径解析：参数 > `AISHELF_SCHEDULES` > 默认。
- `due_schedules(schedules, state, now) -> list[Schedule]`：**纯函数**。对每条 `enabled` 的计划，令 `fire = now 当天的 hour:minute`；当 `now >= fire` 且 `state.get(name) != now.date()`（今天还没跑过）时判定为 due。返回应跑列表。
  - 天然实现补跑：启动时若今天的点已过且今天未跑 → 立即补一次；睡过头同理；一天内多次判定只跑一次。

### 3. 运行状态 `aishelf.site.schedule_state`

- 持久化到 `<data_dir>/schedule_state.json`，形如 `{"karpathy-daily": "2026-06-05"}`（上次成功跑的本地日期）。
- `load_state(data_dir) -> dict[str, str]`：缺文件/坏 JSON → `{}`。
- `save_state(data_dir, state)`：**原子写**（`mkstemp` + `os.replace`，复用 notes 的并发安全模式）。

### 4. 非交互采集 `aishelf.site.collect.run_once`

- 新增 `run_once(prompt, data_dir=None) -> str`：构造 `messages = [system(build_collection_instructions(data_dir)), user(prompt)]`，以 `stream=False` 调用 `hermes.get_client().chat.completions.create(...)`，返回助手文本。
- Hermes 照常自行写文件。函数只触发并返回摘要；**调用方负责 catch**。

### 5. 调度线程 `aishelf.site.scheduler`

- `run_due_now(now=None)`：加载 schedules + state，算 `due_schedules`，对每条调 `collect.run_once`，成功后把 `state[name]=今天` 并 `save_state`。**每条用 try/except 包裹**：单条失败只记日志，不影响其它条、不更新该条状态（下次重试）。
- `start(app)` / 后台线程：循环 `run_due_now()` 然后 `sleep(60s)`，可被停止事件打断。
- 挂在 FastAPI `lifespan`：仅当 `AISHELF_SCHEDULER_ENABLED` 为真时启动线程；关闭时置停止事件并 join。
- `__main__.py` 在 `uvicorn.run` 前 `os.environ.setdefault("AISHELF_SCHEDULER_ENABLED", "1")` —— 真正启动站点默认开；TestClient 不设该变量 → 测试不起线程。

### 6. 鉴权边界

定时任务无人工输入口令，**采集白名单不约束它**。授权点是 `config/schedules.yaml` 本身：只有能写文件系统的人才能新增计划。会在文档与注释中写明。

## 错误处理

- 配置坏条目：跳过 + log，其余照常。
- 单条采集异常：catch + log，不更新该条状态（下次重试），不影响其它条与线程存活。
- Hermes 不可达：`run_once` 抛出 → 被 `run_due_now` 的 per-item catch 接住并记日志。

## 测试

- `load_schedules`：正常多条解析；跳过缺字段/坏 time/重复 name；缺文件 → `[]`；`enabled` 省略默认 true；读 `AISHELF_SCHEDULES` 环境变量路径。
- `due_schedules`（纯函数，重点）：未到点 → 不 due；到点且今天未跑 → due；今天已跑 → 不 due；disabled → 不 due；上次为昨天且已过点 → 补跑 due；多条混合。
- `schedule_state`：save → load round-trip；缺文件 → `{}`；坏 JSON → `{}`；原子写不留 `.tmp`。
- `collect.run_once`：mock Hermes client，断言 messages[0] 是含数据目录的 system、messages[-1] 是 user+prompt、`stream=False`、返回助手文本。
- `scheduler.run_due_now`：mock `collect.run_once`；due 的被调用且状态更新为今天；非 due 不调用；某条 `run_once` 抛异常时其状态不更新而其它条照常。

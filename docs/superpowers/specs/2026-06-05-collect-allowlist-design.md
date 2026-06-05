# 采集白名单（口令制）设计

**目标:** 给 Hermes 采集加访问控制 —— 只有持有白名单口令的调用者才能触发采集，防止局域网内任意访客消耗较高的采集成本。浏览 / 笔记 / 删除均不受影响。

## 背景

站点现已绑定 `0.0.0.0`，局域网内任何人都能打开 `/collect` 并发起 `POST /collect/chat`，每次都会驱动一次 Hermes 采集（成本较高）。需要把"谁能采集"收口到一份后台手动维护的白名单。

## 组件

### 1. 白名单存储（后台手动维护）

- 文件：`config/collect_allowlist.txt`（**gitignore**，含口令）。
- 路径可用环境变量 `AISHELF_COLLECT_ALLOWLIST` 覆盖；默认 `<repo>/config/collect_allowlist.txt`。
- 格式：一行一个口令。`#` 起头的行与空行忽略；行内 `#` 之后视为注释；口令两端空白裁掉。
  ```
  yuan-laptop-9f3a    # 我的本本
  alice-2k4d          # Alice
  ```
- 加白名单 = 加一行；删 = 删一行。**按请求读取**（与站点其它数据一致），改完无需重启，刷新即生效。

### 2. 校验模块 `aishelf.site.allowlist`

- `load_tokens(path=None) -> set[str]`：读文件，解析出有效口令集合；文件不存在 / 读不了 → 返回空集合（不抛）。
- `is_allowed(token: str | None, path=None) -> bool`：`token` 去空白后非空且在集合内才为 `True`。空 token、空集合一律 `False`（**fail-closed**）。
- 解析规则集中在此模块，作为唯一改动点。

### 3. 路由校验（`app.py`）

- `POST /collect/chat`：从请求头 `X-Collect-Token` 取口令，`is_allowed` 为假 → **403**（`detail="采集口令无效，请联系管理员加入白名单"`），**不触碰 Hermes**。通过才构造 payload 走 `stream_chat`。
- `/collect` 页面（GET）保持可访问 —— 它要承载口令输入框；真正的闸口在 `/collect/chat`。

### 4. 前端（`collect.html`）

- 顶部加「采集口令」输入框 + 保存按钮；值存 `localStorage`（键 `aishelf_collect_token`），页面加载时回填。
- 发起 `POST /collect/chat` 时带上 `X-Collect-Token` 头。
- 收到 403 时在对话区显示「口令无效，请联系管理员加入白名单」，并高亮口令输入框，不把 403 当成普通流式错误。

## 默认拒绝（fail-closed）

白名单文件缺失或为空 → 任何口令都不放行。服务端在 `/collect/chat` 命中此情况时 `log` 一句提示，引导管理员去 `config/collect_allowlist.txt` 加口令。

## 安全边界

口令在局域网内明文传输（HTTP + 请求头）。能挡住"逛进来的人误触发采集"，不防内网抓包、不是加密。要更强需 HTTPS + 账号体系，属另一量级，不在本次范围。

## 测试

- `load_tokens`：正常多行解析；忽略空行 / `#` 注释行 / 行内注释；裁剪两端空白；文件不存在 → 空集合。
- `is_allowed`：在册口令 → True；不在册 → False；空 / None token → False；空白名单 → 全 False。
- 路由：带有效口令头 → 200 且流式响应（Hermes mock）；无口令头 → 403；无效口令 → 403；403 时 `stream_chat` 不被调用。
- 默认拒绝：白名单文件不存在时任意口令 → 403。

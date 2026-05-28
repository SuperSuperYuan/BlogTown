# M1 — Scraper 设计

- **日期**: 2026-05-28
- **状态**: 草案,待用户审阅
- **作者**: yuanchao@liblib.ai(与 Claude Code 合作)
- **所属项目**: `aishelf` — AI 视频内容聚合三模块项目(M1 Scraper / M2 Understanding / M3 Web)
- **本期范围**: 仅 M1。M2、M3 在 M1 落地后各自单独 spec。

## 1. 背景与范围

现有 `BlogTown` 仓库是一个 stdlib-only 的小博客练手项目,与现在的目标无关,**整体替换**为 `aishelf` — 一个面向 AI 领域人物访谈/技术分享内容的聚合平台。

整个平台由三个独立模块构成,接口契约清晰:

| 模块 | 输入 | 输出 |
|---|---|---|
| **M1 Scraper(本 spec)** | 配置(账号清单 + 日期区间) | 文件系统:`data/<platform>/<account>/<video_id>/{meta.json, thumb.jpg, transcript.json}` |
| **M2 Understanding** | M1 输出的 meta + transcript | 数据库:结构化主题/摘要/章节 |
| **M3 Web** | M2 数据库 | 浏览器(视频列表 + 主题列表) |

构建顺序 M1 → M2 → M3,每个模块走完整 spec → plan → 实现周期。本文只覆盖 M1。

### 目标

- 给定一份账号清单和日期区间,从 YouTube + Bilibili 抓取符合条件的视频
- 对每个视频持久化:元数据、封面、文本转录(优先平台 CC,缺失则下临时音频 → OpenAI Whisper API 生成)
- 输出格式稳定、对 M2 友好,失败可重跑,重跑不重复下载

### 非目标(YAGNI)

明确**不在本期**:

- 并发 worker pool(同步逐个处理够用)
- B站登录 / cookie(仅匿名)
- 增量状态文件 / 数据库(每次显式 `--since`,无状态)
- Web/TUI 管理界面
- 指标 / Prometheus / 告警
- 扩展平台(X、Vimeo、播客 RSS 等;接口为扩展留好,但本期只做 YouTube + Bilibili)
- 删除/归档已下架视频

## 2. 已确认决策快照

| 维度 | 决策 |
|---|---|
| 与现有 BlogTown 关系 | 直接替换,删除 `blogtown/` `tests/` `data/` `main.py`,改写 CLAUDE.md / README |
| 平台 | YouTube + Bilibili |
| 触发 | CLI,YAML 配置;调度交给外部(cron/launchd) |
| 配置粒度 | 一个平台账号 = 一个 YAML 条目 |
| 时间窗口 | 每次跑显式传 `--since`,可选 `--until`;无增量状态 |
| 下载范围 | 元数据 + 封面 + 转录(无视频文件,无持久化音频) |
| 转录链 | 平台 CC → 没有则下临时音频 → OpenAI Whisper API |
| ASR 后端 | OpenAI Whisper API(`OPENAI_API_KEY`) |
| 账号 ID 输入 | 接受稳定 ID / URL / `@handle`,内部归一化 |
| 适配器接口 | `Protocol`(鸭子类型) |
| 日志输出 | 仅 stdout,标准库 `logging` |
| 失败记录位置 | `data/_failures/<platform>/<account>/<video_id>.json`,与成功体的目录树平级、不交叉 |

## 3. 项目身份与依赖

- **仓库目录**:沿用 `BlogTown/`(磁盘路径不变)
- **Python 包名**:`aishelf`
- **CLI**:`python -m aishelf.scraper`

### 目录结构

```
BlogTown/
  pyproject.toml             # 包元数据 + 依赖
  README.md                  # 改写为 aishelf 介绍
  CLAUDE.md                  # 改写,说明这是多模块项目,M1/M2/M3 概述
  config/
    authors.yaml             # 用户编辑的账号清单,gitignore
    authors.example.yaml     # commit 的示例
  src/aishelf/
    __init__.py
    scraper/
      __init__.py
      __main__.py            # `python -m aishelf.scraper`
      cli.py
      config.py
      pipeline.py
      adapters/
        base.py
        youtube.py
        bilibili.py
      transcribe.py
      store.py
      _retry.py
  data/                      # 运行产出,整体 gitignore
    youtube/
    bilibili/
    _failures/
  tests/
    unit/
    integration/             # @pytest.mark.network,默认 skip
    fixtures/
  docs/superpowers/specs/
```

### 第三方依赖(`pyproject.toml`)

| 依赖 | 用途 |
|---|---|
| `yt-dlp` | YouTube & B站列视频、下音频、抓元数据/封面 |
| `youtube-transcript-api` | YouTube 字幕获取的轻量路径 |
| `openai` | Whisper ASR |
| `httpx` | 下封面图、补充 HTTP |
| `PyYAML` | 解析 authors.yaml |
| `pydantic` v2 | 数据模型 + 配置校验 |

测试:`pytest`、`pytest-mock`、`respx`(httpx mocking)。

Python 版本要求:`>= 3.11`(pydantic v2 兼容性 + `Self` 类型 + `Enum`/`Literal` 用得舒服)。

## 4. 数据契约(M1 → M2)

这是 M1 最关键的部分 — schema 稳了,M2 可以独立开发。

### 4.1 目录与文件布局

```
data/
  youtube/
    UCabc.../                            # 解析后的 YouTube channel ID
      dQw4w9WgXcQ/                       # video ID
        meta.json
        thumb.jpg                        # 扩展名归一化为 .jpg
        transcript.json
  bilibili/
    12345678/                            # 解析后的 B站 UID
      BV1xx411c7XX/                      # B站 BV ID
        meta.json
        thumb.jpg
        transcript.json
  _failures/
    youtube/UCabc.../dQw4w9WgXcQ.json    # 失败记录,与成功体分开
```

**为什么这样切**:
- 平台/账号在路径里,人眼浏览和 `find data/youtube -name meta.json` 都直观
- 每个视频自包含一个目录,原子写(`.tmp` + rename),只有 `meta.json` 写完才视为完成
- 失败放 `_failures/` 之外,M2 扫 `data/<platform>/**/meta.json` 时不会污染

### 4.2 `meta.json` schema(v1)

```json
{
  "schema_version": 1,
  "platform": "youtube",
  "video_id": "dQw4w9WgXcQ",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "account": {
    "id": "UCabc...",
    "display_name": "Lex Fridman"
  },
  "title": "Yann LeCun: AGI is not coming soon",
  "description": "原始描述,平台返回什么存什么",
  "published_at": "2026-05-12T14:32:00Z",
  "duration_seconds": 7245,
  "thumbnail_path": "thumb.jpg",
  "transcript_path": "transcript.json",
  "view_count": 1234567,
  "tags": ["AI", "AGI", "deep learning"],
  "fetched_at": "2026-05-28T10:00:00Z"
}
```

- 所有时间一律 ISO 8601 UTC 字符串
- 缺失字段:`view_count` 用 `null`,`tags` 用 `[]`
- `schema_version` 用于将来字段演进;M2 读到不认识的 version 时报警

### 4.3 `transcript.json` schema(v1)

```json
{
  "schema_version": 1,
  "language": "en",
  "source": "youtube_cc_manual",
  "segments": [
    { "start": 0.0, "end": 4.32, "text": "Welcome back to the podcast." },
    { "start": 4.32, "end": 9.10, "text": "Today we have Yann LeCun." }
  ],
  "full_text": "Welcome back to the podcast. Today we have Yann LeCun. ..."
}
```

- `source` 枚举:`youtube_cc_manual` | `youtube_cc_auto` | `bilibili_cc` | `whisper_api`
- `language`:BCP-47 简码(`en`, `zh`, `zh-CN`)
- 同时保留 `segments`(供未来章节跳转)和 `full_text`(M2 喂 LLM 时不必拼接)

### 4.4 `_failures/<platform>/<account>/<video_id>.json` schema

```json
{
  "schema_version": 1,
  "platform": "youtube",
  "account_id": "UCabc...",
  "video_id": "xyz",
  "url": "https://www.youtube.com/watch?v=xyz",
  "stage": "fetch_subtitle",
  "error_class": "TranscriptsDisabled",
  "error_message": "字幕被作者关闭",
  "retryable": false,
  "last_attempt_at": "2026-05-28T10:00:00Z",
  "attempt_count": 1
}
```

`stage` 枚举:`fetch_meta` | `fetch_thumbnail` | `fetch_subtitle` | `fetch_audio` | `asr` | `write_files`。

### 4.5 去重与重跑语义

| 状态 | `run`(默认) | `run --force` | `retry-failed`(子命令) |
|---|---|---|---|
| 视频目录存在,有 `meta.json` | 跳过 | 重抓覆盖 | 跳过(不动已成功) |
| 视频目录不存在,但有 `_failures/.../<video_id>.json` | 跳过 | 跳过 | 重试 |
| 都不存在 | 抓取 | 抓取 | 跳过(`retry-failed` 不发现新视频) |

**不变量**:同一个 `(platform, account, video_id)` 在 `data/<platform>/<account>/<video_id>/meta.json` 和 `_failures/<platform>/<account>/<video_id>.json` 中**至多存在一个**。
- 成功落盘时,如有同名 failure 文件,删除它
- `retry-failed` 重试成功后,同样删除 failure 文件

### 4.6 缩略图

直接保存平台返回的最大尺寸,**扩展名跟随实际格式**(`thumb.jpg` / `thumb.webp` / `thumb.png`)。`meta.json.thumbnail_path` 写真实的相对文件名(如 `"thumb.webp"`),是 M2 读图的真相来源 — 它不应该靠扩展名猜。Pillow 不在本期依赖,不做格式转换。

## 5. CLI 与配置

### 5.1 CLI 表面

```
python -m aishelf.scraper run --since 2026-01-01 [选项]

  --since YYYY-MM-DD              必填,按视频发布时间过滤
  --until YYYY-MM-DD              可选,默认到今天
  --platform {youtube,bilibili,all}
                                  可选,默认 all
  --account ID                    可选,多次给可指定多个;只跑这些账号
  --force                         重抓已存在 meta.json 的视频
  --dry-run                       调列表 API,但不下载、不调 ASR、不写盘
  --max-videos-per-account N      覆盖 YAML 的 default
  --verbose                       日志切到 DEBUG
```

辅助子命令:

```
python -m aishelf.scraper retry-failed [--platform ...] [--account ID ...]
python -m aishelf.scraper validate-config     # lint authors.yaml
python -m aishelf.scraper list-config         # 打印解析后的账号清单(归一化 ID)
```

子命令路由用 `argparse` 的 subparsers,不引入 click。

### 5.2 退出码

| 码 | 含义 |
|---|---|
| 0 | 全部成功,或所有错误都已记入 `_failures/` |
| 1 | 配置错误 / CLI 用法错误,未执行任何抓取 |
| 2 | 至少一个账号整体失败(平台 API 完全不可达等),应人工查看 |

### 5.3 `config/authors.yaml` schema

```yaml
accounts:
  - platform: youtube
    id: UCSHZKyawb77ixDdsGog4iWA      # 或 URL / @handle,自动归一化
    display_name: Lex Fridman
    enabled: true
    note: AI 访谈主战场

  - platform: bilibili
    id: "12345678"                     # 或 https://space.bilibili.com/12345678
    display_name: 某 AI UP 主
    enabled: true

defaults:
  language_hint: null                  # Whisper 语种提示,null=自动
  max_videos_per_account: 50
  request_timeout_seconds: 30
  min_delay_between_requests_seconds: 1.0
  youtube_api_quota_aware: false       # 预留,首版不实现
```

- `accounts[].id` 接受三种输入(稳定 ID / 完整 URL / `@handle`),由对应 adapter 的 `resolve_account_id()` 归一化
- 磁盘路径**用归一化后的稳定 ID**,与用户输入形式无关 — 改写 YAML 不会让重复抓取
- `enabled: false` 跳过该账号但保留配置
- 非法 YAML 加载时 pydantic 抛清晰错误,不延迟到运行时

### 5.4 账号 ID 归一化

| 平台 | 输入示例 | 归一化后 |
|---|---|---|
| YouTube | `UCSHZKyawb77ixDdsGog4iWA` | `UCSHZKyawb77ixDdsGog4iWA` |
| YouTube | `https://www.youtube.com/@lexfridman` | `UCSHZKyawb77ixDdsGog4iWA` |
| YouTube | `@lexfridman` | `UCSHZKyawb77ixDdsGog4iWA` |
| Bilibili | `12345678` | `12345678` |
| Bilibili | `https://space.bilibili.com/12345678` | `12345678` |

YouTube 用 yt-dlp 探频道页拿到 channel ID;B站从 URL 正则就够。`validate-config` 会回显归一化结果给人核对。

## 6. 组件结构与数据流

### 6.1 组件职责

| 模块 | 输入 | 输出 | 依赖 |
|---|---|---|---|
| `cli.py` | `sys.argv` | 调 `pipeline.run(args)` 或退出码 | argparse |
| `config.py` | YAML 路径 | `ScraperConfig`(已解析的稳定 ID) | pydantic, PyYAML, adapters |
| `pipeline.py` | `ScraperConfig` + CLI 参数 | 文件副作用 + 日志 | adapters, store, transcribe |
| `adapters/base.py` | — | 抽象 `Protocol` | — |
| `adapters/youtube.py` | account_id, since/until | listing + fetch_* 方法 | yt-dlp, youtube-transcript-api, httpx |
| `adapters/bilibili.py` | account_id, since/until | 同上 | yt-dlp, httpx |
| `transcribe.py` | audio path + lang hint | `TranscriptResult` | openai |
| `store.py` | 路径 + 数据对象 | 原子文件写入 | stdlib |
| `_retry.py` | callable + 配置 | 带退避重试的执行 | stdlib |

### 6.2 `PlatformAdapter` 接口(Protocol)

```python
from typing import Protocol, ClassVar, Literal, Iterator
from pathlib import Path
from datetime import date

class PlatformAdapter(Protocol):
    platform: ClassVar[Literal["youtube", "bilibili"]]

    def resolve_account_id(self, raw: str) -> str: ...

    def list_videos(
        self, account_id: str, since: date, until: date, limit: int
    ) -> Iterator[VideoListing]: ...
        # VideoListing 轻量,仅 id + title + published_at,够 dedup 判断

    def fetch_meta(self, video_id: str) -> VideoMeta: ...
    def fetch_thumbnail(self, meta: VideoMeta, dest: Path) -> None: ...

    def fetch_subtitle(self, meta: VideoMeta) -> TranscriptResult | None: ...
        # 返回 None 表示无 CC,需要走 ASR fallback

    def fetch_audio(self, meta: VideoMeta, dest: Path) -> None: ...
        # 仅在 fetch_subtitle() 返回 None 时被调用
```

### 6.3 一条视频从发现到落盘的数据流(`pipeline.process_one`)

```
1. listing: VideoListing  ← adapter.list_videos() 迭代到
2. if exists(data/<platform>/<account>/<video_id>/meta.json) and not --force:
       skip
3. if exists(_failures/<platform>/<account>/<video_id>.json) and not --retry-failed:
       skip
4. meta = adapter.fetch_meta(listing.video_id)
5. tmp_dir = final_dir.with_suffix(".tmp"); tmp_dir.mkdir()
6. adapter.fetch_thumbnail(meta, tmp_dir / "thumb.jpg")
7. transcript = adapter.fetch_subtitle(meta)
8. if transcript is None:
       audio = tmp_dir / "audio.tmp.m4a"
       adapter.fetch_audio(meta, audio)
       transcript = transcribe.WhisperApi().transcribe(audio, lang=defaults.language_hint)
       audio.unlink()
9. store.write_meta(tmp_dir, meta)
   store.write_transcript(tmp_dir, transcript)
10. os.rename(tmp_dir, final_dir)        # 原子提交
```

任一步骤抛异常 → 整段 catch → `store.write_failure(...)` → 清理 tmp_dir → 继续下一条(默认 best-effort)。

### 6.4 文件大小预估

每个视频典型:
- `meta.json`: ~2 KB
- `thumb.jpg`: ~50–200 KB
- `transcript.json`: 1h 视频 ~ 100–300 KB
- **合计 ~ 0.3 MB / 视频**

100 个账号 × 平均 200 条历史 ≈ 6 GB,可承受。

## 7. 错误处理与限流

### 7.1 错误分类

| 类型 | 触发场景 | 处理 |
|---|---|---|
| **可重试** | 网络超时、5xx、HTTP 429、yt-dlp 偶发解析失败 | 同进程内重试 3 次,指数退避 1s/2s/4s |
| **不可重试** | 视频已删除(404)、字幕被关闭、账号不存在 | 立刻记入 `_failures/`,`retryable: false` |

`_retry.py` 提供 ~30 行的 `retry(callable, attempts=3, base=1.0, retry_on=tuple_of_exceptions)`。不引入 tenacity。

### 7.2 限流

- 同平台两次请求之间最少 `min_delay_between_requests_seconds`(默认 1.0,B站可手动调高)
- 依赖 yt-dlp 自身的请求节奏 + 这一层间隔

## 8. 日志

标准库 `logging`,**仅 stdout**。

```
2026-05-28T10:00:01Z INFO  starting account=youtube/UCSHZ.../Lex Fridman since=2026-01-01
2026-05-28T10:00:03Z INFO  found 12 videos in range
2026-05-28T10:00:03Z INFO  processing video_id=abc123 title="Yann LeCun: AGI..."
2026-05-28T10:00:05Z INFO  transcript source=youtube_cc_manual lang=en
2026-05-28T10:00:06Z INFO  done video_id=abc123 elapsed=2.1s
2026-05-28T10:02:30Z INFO  account summary: 12 found, 8 new, 3 skipped, 1 failed
2026-05-28T10:02:30Z INFO  run summary: accounts=5 videos_new=23 videos_failed=2 elapsed=8m32s
```

`key=value` 风格,grep 友好。`--verbose` 切到 DEBUG。

## 9. 测试策略

| 层 | 目的 | 是否打网络 |
|---|---|---|
| **Unit** | config 解析、路径计算、dedup 决策、`_retry`、`store` 原子写、failure schema 校验 | 否 |
| **Adapter contract** | fixture 驱动 youtube.py / bilibili.py,断言它们正确产出 `VideoMeta` / `TranscriptResult` | 否(用 `respx` mock httpx) |
| **Pipeline E2E** | mock 所有外部 IO,跑 CLI 进 tmp dir,断言文件落盘 | 否 |
| **Live smoke** | `@pytest.mark.network`,偶尔手动跑验证真实 API 假设 | 是,默认 skip |

**Whisper API 永远 mock,绝不在测试中真调。**

固件目录:

```
tests/fixtures/
  youtube/{list_response.json, transcript_manual.json, transcript_auto.json, no_transcript.json}
  bilibili/{list_response.json, transcript.json, no_transcript.json}
  whisper/{response_zh.json, response_en.json}
```

`pytest.ini` 默认 `addopts = -m "not network"`。

## 10. 实施完成的判定标准

- [ ] `python -m aishelf.scraper validate-config` 对示例 YAML 通过,对错误 YAML 报清晰错误
- [ ] `python -m aishelf.scraper list-config` 正确回显归一化后的稳定 ID
- [ ] `python -m aishelf.scraper run --since 2025-01-01 --account UC<lex>` 抓到至少 1 条视频,产出 `data/youtube/UC.../<video>/{meta.json, thumb.jpg, transcript.json}`,字段符合 schema
- [ ] 同一命令再跑一次默认跳过所有已抓视频
- [ ] 一个故意失败的视频(如已删除)能记入 `_failures/` 并以退出码 0 结束(因为属于"已记录"的失败)
- [ ] `python -m aishelf.scraper retry-failed` 重试失败记录,成功后自动从 `_failures/` 移除对应文件
- [ ] B站匿名抓一个公开 AI UP 主账号也能跑通同样流程
- [ ] 缺字幕的视频会触发 Whisper API 路径,且测试中此路径被 mock 验证过

## 11. 后续 spec(M2、M3)的接口承诺

M2 启动时,M1 必须保证以下不变量,以便 M2 可以独立设计:

- `data/<platform>/<account>/<video_id>/meta.json` 一旦存在,就表示该视频的所有产物完整(thumb + transcript)
- `meta.json` 和 `transcript.json` 的 `schema_version` 字段决定字段集
- 任何不在 `data/<platform>/...` 树下的目录(如 `_failures/`)对 M2 不可见、可被忽略
- 文件内容在 M1 完成写入后是只读的(M1 不会偷偷改已成功视频)

如果 M2 设计阶段发现 schema 不够,任何字段新增需要 bump `schema_version` 并提供迁移路径。

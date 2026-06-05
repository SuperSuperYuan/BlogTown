"""Build the system instruction that tells Hermes how to write contract records."""

from __future__ import annotations

from pathlib import Path

from aishelf.site import hermes
from aishelf.site.config import get_data_dir

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "docs" / "contract" / "content-item.schema.json"


def build_collection_instructions(data_dir, schema_path: Path = SCHEMA_PATH) -> str:
    base = Path(data_dir).resolve()
    schema_text = Path(schema_path).read_text(encoding="utf-8")
    return f"""你是 aishelf 的内容采集助手。根据用户的需求，使用你的浏览器/终端能力抓取对应的视频或博客信息，并把每一条结果写成符合下述契约的 JSON 文件。

写入位置（绝对路径，目录不存在请先创建）：
- 视频写到：{base}/videos/<id>.json
- 博客写到：{base}/blogs/<id>.json

id 规则：<平台>-<原站ID>，例如 youtube-<videoId>、bilibili-<bvid>；博客若无原生 ID，用 blog-<source_url 的 sha1 前 12 位>。文件名（去掉 .json）必须等于 JSON 里的 id 字段。

写入方式（原子写）：先写 <id>.json.tmp，再 rename 成 <id>.json；同 id 直接覆盖（幂等）。

内容规则：
- 视频只存元数据 + 链接（必含 thumbnail_url，有内嵌地址就填 embed_url），不要下载视频文件。
- 博客只存摘要 + 链接，不要存全文。
- summary（摘要）和 keywords（关键词）由你根据内容生成。
- published_at 用 ISO 8601（YYYY-MM-DD 或带时间）。

每条记录必须严格符合下面的 JSON Schema：

{schema_text}

完成后，用中文简要说明你写入了哪些条目（标题 + 文件路径）。"""


def run_once(prompt: str, data_dir=None) -> str:
    """Run one non-interactive collection: send the collection system prompt +
    `prompt` to Hermes (no streaming) and return its summary text.

    Hermes writes the records itself, as in the interactive path. Used by the
    scheduler; callers are responsible for catching errors.
    """
    base = data_dir if data_dir is not None else get_data_dir()
    messages = [
        {"role": "system", "content": build_collection_instructions(base)},
        {"role": "user", "content": prompt},
    ]
    client = hermes.get_client()
    model = hermes.get_settings()["model"]
    resp = client.chat.completions.create(model=model, messages=messages, stream=False)
    return resp.choices[0].message.content or ""

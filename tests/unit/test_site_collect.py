from pathlib import Path
from types import SimpleNamespace

from aishelf.site.collect import build_collection_instructions


def test_instructions_contain_abs_paths_rules_and_schema(tmp_path):
    schema = tmp_path / "schema.json"
    schema.write_text('{"title": "ContentItem", "marker": "SCHEMA_BODY_123"}', encoding="utf-8")
    data_dir = tmp_path / "mydata"

    text = build_collection_instructions(data_dir, schema_path=schema)

    abs_data = str(data_dir.resolve())
    assert abs_data in text
    assert f"{abs_data}/videos/" in text
    assert f"{abs_data}/blogs/" in text
    # write conventions
    assert ".json.tmp" in text and "rename" in text
    # generated fields + content rules
    assert "summary" in text and "keywords" in text and "thumbnail_url" in text
    # the schema body is embedded verbatim
    assert "SCHEMA_BODY_123" in text


def test_default_schema_path_points_at_committed_schema():
    from aishelf.site import collect
    assert collect.SCHEMA_PATH.name == "content-item.schema.json"
    assert collect.SCHEMA_PATH.exists()


class _FakeClient:
    def __init__(self, content):
        self.captured = {}
        parent = self

        class _Completions:
            def create(self, **kwargs):
                parent.captured = kwargs
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
                )

        self.chat = SimpleNamespace(completions=_Completions())


def test_run_once_calls_hermes_non_streaming(tmp_path, monkeypatch):
    from aishelf.site import collect, hermes

    fake = _FakeClient("已写入 youtube-abc")
    monkeypatch.setattr(hermes, "get_client", lambda: fake)
    monkeypatch.setattr(hermes, "get_settings", lambda: {"model": "hermes-agent"})

    result = collect.run_once("检查 Karpathy 新视频", data_dir=tmp_path)

    assert result == "已写入 youtube-abc"
    sent = fake.captured["messages"]
    assert sent[0]["role"] == "system"
    assert str(tmp_path.resolve()) in sent[0]["content"]   # carries the data dir
    assert sent[-1] == {"role": "user", "content": "检查 Karpathy 新视频"}
    assert fake.captured["stream"] is False                 # non-interactive
    assert fake.captured["model"] == "hermes-agent"

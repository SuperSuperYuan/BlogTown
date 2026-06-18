from aishelf.site import notedraft


_ITEM = {
    "title": "测试时计算扩展",
    "summary": "讨论推理阶段增加算力如何提升模型表现。",
    "keywords": ["推理", "scaling", "评测"],
    "author": "Karpathy",
    "type": "video",
}


def test_build_messages_shape_and_sections():
    msgs = notedraft.build_messages(_ITEM)
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    for tag in ["要点", "为什么值得记", "待探索"]:
        assert tag in system
    assert "Markdown" in system or "markdown" in system
    assert "测试时计算扩展" in user
    assert "推理" in user
    assert "Karpathy" in user


def test_build_messages_includes_existing_note_and_no_repeat():
    msgs = notedraft.build_messages(_ITEM, "我已经记过：scaling 曲线在数学题上最明显。")
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "scaling 曲线在数学题上最明显" in user
    assert "重复" in system


def test_build_messages_empty_note_omits_existing_section():
    msgs = notedraft.build_messages(_ITEM, "")
    user = msgs[1]["content"]
    assert "已有笔记" not in user


import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contract"


@pytest.fixture
def client(monkeypatch, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURES, data)
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    from aishelf.site import app as app_module
    monkeypatch.setattr(
        app_module.llm, "stream_completion",
        lambda messages: iter([app_module.hermes.sse({"delta": "## 要点\n- 草稿"}),
                               app_module.hermes.sse({"done": True})]),
    )
    return TestClient(app_module.app)


def test_note_draft_streams_for_known_id(client):
    r = client.post("/notes/youtube-aaa/draft")
    assert r.status_code == 200
    assert "草稿" in r.text
    assert "done" in r.text


def test_note_draft_unknown_id_404(client):
    assert client.post("/notes/nope-zzz/draft").status_code == 404


def test_note_draft_unsafe_id_404(client):
    assert client.post("/notes/a..b/draft").status_code == 404

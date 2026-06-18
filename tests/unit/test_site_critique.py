from aishelf.site import critique


_ITEM = {
    "title": "测试时计算扩展",
    "summary": "讨论推理阶段增加算力如何提升模型表现。",
    "keywords": ["推理", "scaling", "评测"],
    "author": "Karpathy",
    "type": "video",
}


def test_build_messages_shape_and_sections():
    msgs = critique.build_messages(_ITEM)
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    for tag in ["最薄弱的地方", "反方会怎么说", "什么能说服你改主意"]:
        assert tag in system
    assert "steel" in system.lower() or "稻草人" in system
    assert "Markdown" in system or "markdown" in system
    assert "测试时计算扩展" in user
    assert "推理" in user
    assert "Karpathy" in user


def test_build_messages_with_note_challenges_user_take():
    msgs = critique.build_messages(_ITEM, "我觉得 scaling 一定能解决推理。")
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "我觉得 scaling 一定能解决推理" in user
    assert "笔记" in system


def test_build_messages_empty_note_omits_note_block():
    msgs = critique.build_messages(_ITEM, "")
    assert "我的笔记" not in msgs[1]["content"]


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
        lambda messages: iter([app_module.hermes.sse({"delta": "【最薄弱的地方】证据不足"}),
                               app_module.hermes.sse({"done": True})]),
    )
    return TestClient(app_module.app)


def test_critique_streams_for_known_id(client):
    r = client.post("/critique/youtube-aaa")
    assert r.status_code == 200
    assert "最薄弱的地方" in r.text
    assert "done" in r.text


def test_critique_unknown_id_404(client):
    assert client.post("/critique/nope-zzz").status_code == 404


def test_critique_unsafe_id_404(client):
    assert client.post("/critique/a..b").status_code == 404


def test_video_detail_has_critique_button(client):
    r = client.get("/videos/youtube-aaa")
    assert r.status_code == 200
    assert "唱个反调" in r.text
    assert "/critique/" in r.text


def test_blog_detail_has_critique_button(client):
    r = client.get("/blogs/blog-ccc")
    assert r.status_code == 200
    assert "唱个反调" in r.text
    assert "/critique/" in r.text

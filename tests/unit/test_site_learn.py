from aishelf.site import learn


_ITEMS = [
    {"id": "v1", "title": "推理模型入门", "summary": "什么是推理模型。", "type": "video"},
    {"id": "v2", "title": "测试时计算", "summary": "推理阶段扩展算力。", "type": "video"},
    {"id": "b1", "title": "思维链评测", "summary": "如何评测推理。", "type": "blog"},
]


def test_build_messages_shape_and_content():
    msgs = learn.build_messages("推理模型", _ITEMS)
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "顺序" in system or "进阶" in system
    assert "标题" in system
    assert "Markdown" in system or "markdown" in system
    assert "推理模型" in user
    assert "推理模型入门" in user and "思维链评测" in user

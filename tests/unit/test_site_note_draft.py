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

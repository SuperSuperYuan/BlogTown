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

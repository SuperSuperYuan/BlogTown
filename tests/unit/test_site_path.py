from aishelf.site import path


def _items():
    return [
        {"title": "提示工程", "summary": "s1", "author": "甲", "type": "blog"},
        {"title": "上下文压缩", "summary": "s2", "author": "乙", "type": "video"},
        {"title": "多智能体", "summary": "s3", "author": "丙", "type": "blog"},
    ]


def test_build_messages_has_system_then_user():
    msgs = path.build_messages(_items())
    assert [m["role"] for m in msgs] == ["system", "user"]


def test_build_messages_lists_steps_in_path_order():
    user = path.build_messages(_items())[1]["content"]
    assert user.index("提示工程") < user.index("上下文压缩") < user.index("多智能体")


def test_build_messages_marks_start_and_end():
    user = path.build_messages(_items())[1]["content"]
    assert "起点" in user and "终点" in user


def test_build_messages_system_forbids_markdown():
    sys = path.build_messages(_items())[0]["content"]
    assert "Markdown" in sys or "markdown" in sys

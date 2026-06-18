from aishelf.site import mirror


def _profile():
    return mirror.Profile(
        galaxies=[
            mirror.Galaxy(name="推理模型", color="#ff9a3c", size=12, recent=4,
                          titles=["o1 深度解析", "测试时计算", "思维链评测"]),
            mirror.Galaxy(name="多模态", color="#4cc2ff", size=3, recent=0,
                          titles=["看图说话", "视频理解"]),
        ],
        total=15, videos=9, blogs=6,
        top_authors=[("Karpathy", 4), ("OpenAI", 3)],
        span_days=120, recent_n=10,
    )


def test_build_messages_shape_and_content():
    msgs = mirror.build_messages(_profile())
    assert [m["role"] for m in msgs] == ["system", "user"]
    system, user = msgs[0]["content"], msgs[1]["content"]
    for tag in ["【你的主线】", "【最近的转向】", "【一个盲区】", "【一句话人格】"]:
        assert tag in system
    assert "Markdown" in system or "markdown" in system
    assert "推理模型" in user and "多模态" in user
    assert "12" in user and "o1 深度解析" in user
    assert "Karpathy" in user

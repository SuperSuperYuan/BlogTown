import json

from aishelf.site import ask
from aishelf.site.ask import Source


def _src(i, note=""):
    return Source(id=f"v{i}", type="video", title=f"标题{i}", author="作者甲",
                  platform="youtube", summary=f"摘要{i}", keywords=["k"], note=note)


def test_latest_user_question_returns_last_user_message():
    msgs = [{"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "答"},
            {"role": "user", "content": "第二问"}]
    assert ask.latest_user_question(msgs) == "第二问"


def test_latest_user_question_empty_when_no_user_role():
    assert ask.latest_user_question([{"role": "assistant", "content": "x"}]) == ""


def test_latest_user_question_empty_when_content_none():
    # OpenAI messages may carry content: None (e.g. tool-call turns); must not return None
    assert ask.latest_user_question([{"role": "user", "content": None}]) == ""


def test_build_messages_includes_numbered_sources_note_and_guard():
    msgs = [{"role": "user", "content": "讲了什么？"}]
    out = ask.build_messages(msgs, [_src(1, note="我的笔记内容")])
    assert out[0]["role"] == "system"
    sys = out[0]["content"]
    assert "[1]" in sys and "标题1" in sys
    assert "我的笔记内容" in sys          # the user's note is included as grounding
    assert "[n]" in sys                    # citation instruction present
    assert "内容库" in sys                  # no-source guard wording present
    assert out[1:] == msgs                 # history + question preserved after system


def test_build_messages_marks_empty_sources():
    msgs = [{"role": "user", "content": "x"}]
    out = ask.build_messages(msgs, [])
    assert "暂无" in out[0]["content"]      # explicit "no sources retrieved" marker
    assert out[1:] == msgs


def test_source_refs_shape():
    refs = ask.source_refs([_src(1), _src(2)])
    assert refs == [
        {"id": "v1", "type": "video", "title": "标题1", "author": "作者甲"},
        {"id": "v2", "type": "video", "title": "标题2", "author": "作者甲"},
    ]


def _blog_src(i):
    return Source(id=f"b{i}", type="blog", title=f"博文{i}", author="作者乙",
                  platform="blog", summary=f"摘要{i}", keywords=["k"], note="")


def test_nav_types_video_intent():
    assert ask.nav_types("我要查看 Karpathy 的视频") == {"video"}
    assert ask.nav_types("播放这个视频") == {"video"}
    assert ask.nav_types("go to that video") == {"video"}


def test_nav_types_blog_intent():
    assert ask.nav_types("打开那篇 RAG 博客") == {"blog"}
    assert ask.nav_types("我要看这篇文章") == {"blog"}
    assert ask.nav_types("open that article") == {"blog"}


def test_nav_types_both():
    assert ask.nav_types("打开关于 agent 的视频和文章") == {"video", "blog"}


def test_nav_types_none_without_nav_verb():
    assert ask.nav_types("RAG 是什么") == set()
    assert ask.nav_types("总结一下 agent 相关视频") == set()
    assert ask.nav_types("这个视频讲了什么") == set()  # cue but no nav verb


def test_nav_types_none_without_modality_cue():
    # nav verb present but NO modality cue -> empty set (both sides of the AND)
    assert ask.nav_types("watch it") == set()
    assert ask.nav_types("打开看看") == set()
    assert ask.nav_types("open this") == set()


def test_nav_types_ascii_verb_word_boundary():
    # "play" must not match inside "display"/"replay"/"gameplay"
    assert ask.nav_types("display the video") == set()
    assert ask.nav_types("replay analysis of the article") == set()
    # a real ASCII nav verb with a cue still works
    assert ask.nav_types("play that video") == {"video"}


def test_nav_types_cjk_verb_surrounded_by_chinese():
    # CJK verb must still match when surrounded by other Chinese (no \b around CJK)
    assert ask.nav_types("请打开那个视频") == {"video"}


def test_nav_candidates_filters_by_type_and_caps():
    sources = [_src(1), _blog_src(1), _src(2), _blog_src(2)]
    vids = ask.nav_candidates(sources, {"video"})
    assert [s.id for s in vids] == ["v1", "v2"]
    both = ask.nav_candidates(sources, {"video", "blog"})
    assert [s.id for s in both] == ["v1", "b1", "v2", "b2"]  # retrieval order preserved
    assert ask.nav_candidates(sources, set()) == []


def test_nav_candidates_caps_at_nav_max():
    many = [_src(i) for i in range(ask.NAV_MAX + 3)]
    assert len(ask.nav_candidates(many, {"video"})) == ask.NAV_MAX


def test_nav_refs_shape():
    assert ask.nav_refs([_src(1)]) == [
        {"id": "v1", "type": "video", "title": "标题1", "author": "作者甲", "platform": "youtube"},
    ]


def test_retrieve_finds_note_only_match(tmp_path, monkeypatch):
    # an item whose summary lacks the term, but whose note contains it
    data = tmp_path / "data"
    (data / "videos").mkdir(parents=True)
    rec = {"id": "v1", "type": "video", "title": "标题", "author": "作者甲",
           "platform": "youtube", "source_url": "https://x/v1", "published_at": "2024-01-01",
           "summary": "普通摘要", "keywords": [], "collected_at": "2024-01-02T00:00:00",
           "thumbnail_url": "https://img/x.jpg"}
    (data / "videos" / "v1.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    (data / "notes").mkdir()
    (data / "notes" / "v1.json").write_text(
        json.dumps({"id": "v1", "text": "讲到了向量数据库", "updated_at": "2024-01-03"}, ensure_ascii=False),
        encoding="utf-8")
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    from aishelf.db.sync import sync
    db = tmp_path / "atlas.db"
    sync(data, db)
    sources = ask.retrieve(db, "向量", k=5)
    assert [s.id for s in sources] == ["v1"]
    assert sources[0].note == "讲到了向量数据库"   # note loaded fresh into the source


def test_is_low_confidence_empty_sources():
    assert ask.is_low_confidence("任意问题", []) is True


def test_is_low_confidence_no_overlap():
    src = Source(id="v1", type="video", title="大语言模型与检索增强", author="作者甲",
                 platform="youtube", summary="一段摘要", keywords=[], note="")
    assert ask.is_low_confidence("量子计算最新进展", [src]) is True


def test_is_low_confidence_strong_overlap():
    src = Source(id="v1", type="video", title="大语言模型与检索增强", author="作者甲",
                 platform="youtube", summary="一段摘要", keywords=[], note="")
    assert ask.is_low_confidence("大语言模型", [src]) is False


def test_is_low_confidence_empty_question():
    src = Source(id="v1", type="video", title="标题", author="作者甲",
                 platform="youtube", summary="摘要", keywords=[], note="")
    assert ask.is_low_confidence("", [src]) is True  # no query tokens -> low confidence


def test_is_low_confidence_borderline():
    # query "一二三四五六七八" -> 7 bigrams; source shares only "一二" -> 1/7 ≈ 0.143 < 0.15 -> True
    src = Source(id="v1", type="video", title="一二 nothing else", author="x",
                 platform="y", summary="", keywords=[], note="")
    assert ask.is_low_confidence("一二三四五六七八", [src]) is True
    # query "一二三四五六七" -> 6 bigrams; shares "一二" -> 1/6 ≈ 0.167 >= 0.15 -> False
    assert ask.is_low_confidence("一二三四五六七", [src]) is False

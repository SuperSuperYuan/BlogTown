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


def test_relevant_sources_drops_unrelated():
    related = Source(id="v1", type="video", title="大语言模型与检索增强", author="作者甲",
                     platform="youtube", summary="讲解大语言模型", keywords=[], note="")
    unrelated = Source(id="v2", type="video", title="园艺与种花入门", author="作者乙",
                       platform="youtube", summary="如何养花", keywords=[], note="")
    kept = ask.relevant_sources("大语言模型", [related, unrelated])
    assert [s.id for s in kept] == ["v1"]


def test_relevant_sources_empty_question_keeps_nothing():
    src = Source(id="v1", type="video", title="标题", author="x", platform="y",
                 summary="摘要", keywords=[], note="")
    assert ask.relevant_sources("", [src]) == []


def test_retrieve_prunes_irrelevant_tail(tmp_path, monkeypatch):
    # Two items share the common bigram "数据" but only one is about the question.
    data = tmp_path / "data"
    (data / "videos").mkdir(parents=True)
    recs = [
        {"id": "v1", "type": "video", "title": "向量数据库实战", "author": "甲",
         "platform": "youtube", "source_url": "https://x/v1", "published_at": "2024-01-01",
         "summary": "讲解向量数据库", "keywords": [], "collected_at": "2024-01-02T00:00:00",
         "thumbnail_url": "https://img/x.jpg"},
        {"id": "v2", "type": "video", "title": "数据隐私与合规", "author": "乙",
         "platform": "youtube", "source_url": "https://x/v2", "published_at": "2024-01-01",
         "summary": "讲解数据隐私", "keywords": [], "collected_at": "2024-01-02T00:00:00",
         "thumbnail_url": "https://img/y.jpg"},
    ]
    for r in recs:
        (data / "videos" / f"{r['id']}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("AISHELF_DATA_DIR", str(data))
    from aishelf.db.sync import sync
    db = tmp_path / "atlas.db"
    sync(data, db)
    # 11 bigrams; v2 shares only "数据" (1/11 ≈ 0.09 < 0.15) so its tail match is pruned.
    sources = ask.retrieve(db, "向量数据库的工程实践经验", k=5)
    assert [s.id for s in sources] == ["v1"]


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


from aishelf import embed as _embed
from aishelf.db.sync import sync as _sync


def _build_db(tmp_path, monkeypatch, items, embed_map):
    """Write videos + a fake-embedded atlas.db. embed_map: text-substring -> vec."""
    data = tmp_path / "data"
    (data / "videos").mkdir(parents=True)
    for it in items:
        (data / "videos" / f"{it['id']}.json").write_text(
            json.dumps(it, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(_embed, "model_name", lambda: "fake-embed")

    def _texts(texts):
        out = []
        for t in texts:
            vec = next((v for sub, v in embed_map.items() if sub in t), [0.0, 0.0, 1.0])
            out.append(vec)
        return out

    monkeypatch.setattr(_embed, "embed_texts", _texts)
    db = tmp_path / "atlas.db"
    _sync(data, db)
    return db


def _vid(vid, title, summary):
    return {"id": vid, "type": "video", "title": title, "author": "作者",
            "platform": "youtube", "source_url": f"https://x/{vid}",
            "published_at": "2024-01-01", "summary": summary, "keywords": [],
            "collected_at": "2024-01-02T00:00:00", "thumbnail_url": "https://img/x.jpg"}


def test_retrieve_hybrid_recalls_semantic_match(tmp_path, monkeypatch):
    # FTS would not match an English title from a Chinese query, but the vector does.
    db = _build_db(tmp_path, monkeypatch,
                   [_vid("v1", "Scaling laws explained", "training compute"),
                    _vid("v2", "园艺入门", "如何种花")],
                   {"Scaling": [1.0, 0.0, 0.0], "园艺": [0.0, 1.0, 0.0]})
    monkeypatch.setattr(ask.embed, "embed_query", lambda q: [1.0, 0.0, 0.0])
    sources = ask.retrieve(db, "扩展定律", k=6)
    assert [s.id for s in sources] == ["v1"]   # semantic hit; gardening pruned by floor


def test_retrieve_hybrid_keeps_fts_safety_net(tmp_path, monkeypatch):
    # v2 is a weak vector match (below floor) but an exact FTS hit -> kept.
    db = _build_db(tmp_path, monkeypatch,
                   [_vid("v1", "Scaling laws", "compute"),
                    _vid("v2", "向量数据库实战", "讲解向量数据库")],
                   {"Scaling": [1.0, 0.0, 0.0], "向量": [0.0, 0.0, 1.0]})
    monkeypatch.setattr(ask.embed, "embed_query", lambda q: [1.0, 0.0, 0.0])
    ids = [s.id for s in ask.retrieve(db, "向量数据库", k=6)]
    assert "v2" in ids    # exact FTS hit survives despite low cosine


def test_retrieve_falls_back_to_fts_when_embedding_unavailable(tmp_path, monkeypatch):
    db = _build_db(tmp_path, monkeypatch,
                   [_vid("v1", "向量数据库实战", "讲解向量数据库")],
                   {"向量": [1.0, 0.0, 0.0]})
    monkeypatch.setattr(ask.embed, "embed_query", lambda q: None)  # service down
    sources = ask.retrieve(db, "向量数据库", k=6)
    assert [s.id for s in sources] == ["v1"]  # pure-FTS path, today's behavior

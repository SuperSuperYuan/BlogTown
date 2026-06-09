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

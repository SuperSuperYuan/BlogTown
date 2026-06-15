import json
from types import SimpleNamespace

from aishelf import alias


class _Completions:
    def __init__(self, content):
        self.content = content
        self.captured = {}

    def create(self, **kwargs):
        self.captured = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


class _FakeClient:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=_Completions(content))


def _configure(monkeypatch):
    monkeypatch.setenv("ATLAS_CHAT_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("ATLAS_CHAT_API_KEY", "k")
    monkeypatch.setenv("ATLAS_CHAT_MODEL", "fake-chat")


def test_not_configured_returns_none(monkeypatch):
    monkeypatch.delenv("ATLAS_CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("ATLAS_CHAT_MODEL", raising=False)
    assert alias.is_configured() is False
    assert alias.generate_aliases([("t", "s")]) is None


def test_generate_aliases_parses_json_array(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('["RAG综述", "Agent构建"]'))
    assert alias.generate_aliases([("RAG paper", "x"), ("Agent guide", "y")]) == ["RAG综述", "Agent构建"]


def test_generate_aliases_strips_code_fence(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('```json\n["甲", "乙"]\n```'))
    assert alias.generate_aliases([("a", ""), ("b", "")]) == ["甲", "乙"]


def test_generate_aliases_caps_length(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('["一二三四五六七八九十甲乙"]'))
    out = alias.generate_aliases([("a", "")])
    assert len(out) == 1 and len(out[0]) <= 10


def test_empty_input_returns_none(monkeypatch):
    _configure(monkeypatch)
    assert alias.generate_aliases([]) is None


def test_wrong_length_returns_none(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "get_client", lambda s: _FakeClient('["仅一个"]'))
    assert alias.generate_aliases([("a", ""), ("b", "")]) is None  # 1 alias for 2 inputs


def test_client_error_returns_none(monkeypatch):
    _configure(monkeypatch)

    def _boom(s):
        raise RuntimeError("down")

    monkeypatch.setattr(alias, "get_client", _boom)
    assert alias.generate_aliases([("a", "")]) is None


class _CountingCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        count = kwargs["messages"][0]["content"].count("｜")   # one separator per item line
        arr = json.dumps([f"别名{i}" for i in range(count)], ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=arr))])


class _CountingClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_CountingCompletions())


def test_generate_aliases_batches_and_reassembles(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "ALIAS_BATCH_SIZE", 2)
    client = _CountingClient()
    monkeypatch.setattr(alias, "get_client", lambda s: client)
    out = alias.generate_aliases([(f"t{i}", "s") for i in range(5)])
    assert out is not None and len(out) == 5            # 2+2+1 batches reassembled in order
    assert client.chat.completions.calls == 3


def test_generate_aliases_batch_failure_returns_none(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(alias, "ALIAS_BATCH_SIZE", 2)

    class _FailSecond:
        def __init__(self):
            self.n = 0

        def create(self, **kwargs):
            self.n += 1
            if self.n == 2:
                raise RuntimeError("batch 2 down")
            count = kwargs["messages"][0]["content"].count("｜")
            arr = json.dumps([f"x{i}" for i in range(count)], ensure_ascii=False)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=arr))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=_FailSecond()))
    monkeypatch.setattr(alias, "get_client", lambda s: client)
    assert alias.generate_aliases([("a", ""), ("b", ""), ("c", "")]) is None  # batch-2 failure -> all None

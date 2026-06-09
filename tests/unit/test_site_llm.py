from types import SimpleNamespace

from aishelf.site import llm


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.captured = {}
        parent = self

        class _Completions:
            def create(self, **kwargs):
                parent.captured = kwargs
                return iter(parent._chunks)

        self.chat = SimpleNamespace(completions=_Completions())


def test_chat_settings_default_to_hermes(monkeypatch):
    for k in ("ATLAS_CHAT_BASE_URL", "ATLAS_CHAT_API_KEY", "ATLAS_CHAT_MODEL",
              "HERMES_BASE_URL", "HERMES_API_KEY", "HERMES_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HERMES_BASE_URL", "http://hermes:9/v1")
    monkeypatch.setenv("HERMES_MODEL", "hermes-agent")
    s = llm.get_chat_settings()
    assert s["base_url"] == "http://hermes:9/v1"
    assert s["model"] == "hermes-agent"


def test_chat_settings_override(monkeypatch):
    monkeypatch.setenv("ATLAS_CHAT_BASE_URL", "http://chat:1/v1")
    monkeypatch.setenv("ATLAS_CHAT_MODEL", "fast-chat")
    s = llm.get_chat_settings()
    assert s["base_url"] == "http://chat:1/v1"
    assert s["model"] == "fast-chat"


def test_stream_completion_yields_delta_and_done(monkeypatch):
    monkeypatch.setattr(llm, "get_client", lambda: _FakeClient([_chunk("你好"), _chunk("世界")]))
    out = "".join(llm.stream_completion([{"role": "user", "content": "hi"}]))
    assert "你好" in out and "世界" in out
    assert '"done": true' in out


def test_stream_completion_error_event(monkeypatch):
    class _Boom:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(
                create=lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))))
    monkeypatch.setattr(llm, "get_client", lambda: _Boom())
    out = "".join(llm.stream_completion([{"role": "user", "content": "hi"}]))
    assert '"error"' in out

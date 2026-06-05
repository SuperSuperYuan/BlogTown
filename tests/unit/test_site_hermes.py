import json
from types import SimpleNamespace

import httpx
from openai import APIConnectionError

from aishelf.site import hermes


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


class _FakeCompletions:
    def __init__(self, chunks=None, exc=None):
        self._chunks = chunks or []
        self._exc = exc

    def create(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return iter(self._chunks)


class _FakeClient:
    def __init__(self, chunks=None, exc=None):
        self.chat = SimpleNamespace(completions=_FakeCompletions(chunks, exc))


def _events(chunks):
    out = []
    for piece in "".join(chunks).split("\n\n"):
        piece = piece.strip()
        if piece.startswith("data: "):
            out.append(json.loads(piece[len("data: "):]))
    return out


def test_stream_chat_yields_deltas_then_done(monkeypatch):
    fake = _FakeClient(chunks=[_chunk("Hi"), _chunk(None), _chunk(" there")])
    monkeypatch.setattr(hermes, "get_client", lambda: fake)
    events = _events(list(hermes.stream_chat([{"role": "user", "content": "x"}])))
    assert {"delta": "Hi"} in events
    assert {"delta": " there"} in events
    assert {"done": True} in events


def test_stream_chat_skips_chunks_without_choices(monkeypatch):
    none_chunk = SimpleNamespace(choices=None)
    fake = _FakeClient(chunks=[_chunk("a"), none_chunk, _chunk("b")])
    monkeypatch.setattr(hermes, "get_client", lambda: fake)
    events = _events(list(hermes.stream_chat([{"role": "user", "content": "x"}])))
    assert {"delta": "a"} in events and {"delta": "b"} in events
    assert not any("error" in e for e in events)


def test_stream_chat_connection_error_emits_error_event(monkeypatch):
    exc = APIConnectionError(request=httpx.Request("POST", "http://localhost"))
    monkeypatch.setattr(hermes, "get_client", lambda: _FakeClient(exc=exc))
    events = _events(list(hermes.stream_chat([{"role": "user", "content": "x"}])))
    assert any("error" in e for e in events)

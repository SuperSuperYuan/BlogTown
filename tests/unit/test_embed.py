from aishelf import embed


class _FakeEmbeddings:
    def __init__(self, vectors):
        self._vectors = vectors

    def create(self, *, model, input):
        # Mirror the OpenAI SDK shape: resp.data[i].embedding
        class _D:
            def __init__(self, v):
                self.embedding = v
        class _Resp:
            def __init__(self, vs):
                self.data = [_D(v) for v in vs]
        assert isinstance(input, list)
        return _Resp(self._vectors[: len(input)])


class _FakeClient:
    def __init__(self, vectors):
        self.embeddings = _FakeEmbeddings(vectors)


def _configure(monkeypatch):
    monkeypatch.setenv("ATLAS_EMBED_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("ATLAS_EMBED_API_KEY", "k")
    monkeypatch.setenv("ATLAS_EMBED_MODEL", "fake-embed")


def test_not_configured_returns_none(monkeypatch):
    monkeypatch.delenv("ATLAS_EMBED_BASE_URL", raising=False)
    monkeypatch.delenv("ATLAS_EMBED_MODEL", raising=False)
    assert embed.is_configured() is False
    assert embed.model_name() is None
    assert embed.embed_texts(["x"]) is None
    assert embed.embed_query("x") is None


def test_embed_texts_returns_vectors(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(embed, "get_client", lambda s: _FakeClient([[1.0, 2.0], [3.0, 4.0]]))
    assert embed.is_configured() is True
    assert embed.model_name() == "fake-embed"
    assert embed.embed_texts(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]


def test_embed_query_unwraps_single(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(embed, "get_client", lambda s: _FakeClient([[5.0, 6.0]]))
    assert embed.embed_query("hi") == [5.0, 6.0]


def test_empty_input_returns_none(monkeypatch):
    _configure(monkeypatch)
    assert embed.embed_texts([]) is None
    assert embed.embed_query("") is None


def test_client_error_returns_none(monkeypatch):
    _configure(monkeypatch)

    def _boom(s):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(embed, "get_client", _boom)
    assert embed.embed_texts(["a"]) is None
    assert embed.embed_query("a") is None

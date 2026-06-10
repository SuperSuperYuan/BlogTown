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


class _RecordingEmbeddings:
    """Records each call's input; returns a 1-d vector per text (its length)."""
    def __init__(self):
        self.calls: list[list[str]] = []

    def create(self, *, model, input):
        self.calls.append(list(input))
        class _D:
            def __init__(self, v):
                self.embedding = v
        class _Resp:
            def __init__(self, vs):
                self.data = [_D(v) for v in vs]
        return _Resp([[float(len(t))] for t in input])


class _RecordingClient:
    def __init__(self):
        self.embeddings = _RecordingEmbeddings()


def test_embed_texts_chunks_to_batch_size(monkeypatch):
    # Providers like DashScope cap inputs per request (10); embed_texts must split.
    _configure(monkeypatch)
    rec = _RecordingClient()
    monkeypatch.setattr(embed, "get_client", lambda s: rec)
    monkeypatch.setattr(embed, "EMBED_BATCH_SIZE", 10)
    texts = [f"t{i}" for i in range(23)]
    out = embed.embed_texts(texts)
    assert len(out) == 23                                   # all vectors returned
    assert [len(c) for c in rec.embeddings.calls] == [10, 10, 3]  # split into batches
    assert out[0] == [2.0] and out[22] == [3.0]             # order preserved (len("t0")=2, len("t22")=3)


def test_embed_texts_chunk_failure_returns_none(monkeypatch):
    # If any sub-batch fails, the whole call degrades to None (all-or-nothing).
    _configure(monkeypatch)

    class _FailOnSecond:
        def __init__(self):
            self.n = 0

        def create(self, *, model, input):
            self.n += 1
            if self.n == 2:
                raise RuntimeError("boom")
            class _D:
                def __init__(self, v):
                    self.embedding = v
            class _Resp:
                def __init__(self, vs):
                    self.data = [_D(v) for v in vs]
            return _Resp([[1.0] for _ in input])

    client = type("C", (), {"embeddings": _FailOnSecond()})()
    monkeypatch.setattr(embed, "get_client", lambda s: client)
    monkeypatch.setattr(embed, "EMBED_BATCH_SIZE", 10)
    assert embed.embed_texts([f"t{i}" for i in range(15)]) is None

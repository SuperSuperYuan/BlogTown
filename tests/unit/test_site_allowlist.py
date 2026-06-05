from aishelf.site import allowlist


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def test_load_tokens_parses_one_per_line(tmp_path):
    f = tmp_path / "allow.txt"
    _write(f, "alpha\nbeta\ngamma\n")
    assert allowlist.load_tokens(f) == {"alpha", "beta", "gamma"}


def test_load_tokens_ignores_blanks_and_comments(tmp_path):
    f = tmp_path / "allow.txt"
    _write(f, "# header comment\n\nalpha\n   \n# another\nbeta\n")
    assert allowlist.load_tokens(f) == {"alpha", "beta"}


def test_load_tokens_strips_inline_comments_and_whitespace(tmp_path):
    f = tmp_path / "allow.txt"
    _write(f, "  alpha    # my laptop\nbeta#bob\n")
    assert allowlist.load_tokens(f) == {"alpha", "beta"}


def test_load_tokens_missing_file_is_empty(tmp_path):
    assert allowlist.load_tokens(tmp_path / "nope.txt") == set()


def test_is_allowed_true_for_listed_token(tmp_path):
    f = tmp_path / "allow.txt"
    _write(f, "secret-123\n")
    assert allowlist.is_allowed("secret-123", f) is True


def test_is_allowed_trims_token_whitespace(tmp_path):
    f = tmp_path / "allow.txt"
    _write(f, "secret-123\n")
    assert allowlist.is_allowed("  secret-123  ", f) is True


def test_is_allowed_false_for_unlisted_token(tmp_path):
    f = tmp_path / "allow.txt"
    _write(f, "secret-123\n")
    assert allowlist.is_allowed("nope", f) is False


def test_is_allowed_false_for_empty_token(tmp_path):
    f = tmp_path / "allow.txt"
    _write(f, "secret-123\n")
    assert allowlist.is_allowed("", f) is False
    assert allowlist.is_allowed(None, f) is False
    assert allowlist.is_allowed("   ", f) is False


def test_is_allowed_false_when_allowlist_empty(tmp_path):
    # fail-closed: a missing/empty allowlist denies everyone
    assert allowlist.is_allowed("anything", tmp_path / "nope.txt") is False
    empty = tmp_path / "empty.txt"
    _write(empty, "# only comments\n\n")
    assert allowlist.is_allowed("anything", empty) is False


def test_load_tokens_reads_env_path(tmp_path, monkeypatch):
    f = tmp_path / "env-allow.txt"
    _write(f, "from-env\n")
    monkeypatch.setenv("AISHELF_COLLECT_ALLOWLIST", str(f))
    assert allowlist.load_tokens() == {"from-env"}
    assert allowlist.is_allowed("from-env") is True

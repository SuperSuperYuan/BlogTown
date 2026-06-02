from aishelf.webui import config


def test_get_settings_defaults(monkeypatch):
    for var in ("HERMES_BASE_URL", "HERMES_API_KEY", "HERMES_MODEL"):
        monkeypatch.delenv(var, raising=False)
    s = config.get_settings()
    assert s["base_url"] == "http://127.0.0.1:8642/v1"
    assert s["model"] == "hermes-agent"
    assert s["api_key"]  # non-empty default


def test_get_settings_env_override(monkeypatch):
    monkeypatch.setenv("HERMES_BASE_URL", "http://example/v1")
    monkeypatch.setenv("HERMES_API_KEY", "k")
    monkeypatch.setenv("HERMES_MODEL", "m")
    s = config.get_settings()
    assert s == {"base_url": "http://example/v1", "api_key": "k", "model": "m"}

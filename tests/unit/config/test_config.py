"""Tests for config.py — defaults, toml merge, pydantic validation."""

import secretary.config as c


def test_load_config_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    cfg = c.load_config()
    assert cfg.app.timezone == "Asia/Kolkata"
    assert cfg.app.theme == "system"
    assert cfg.app.start_minimized is True
    assert cfg.llm.active == "groq"
    assert cfg.llm.history_messages == 8
    assert cfg.llm.providers["groq"].base_url == "https://api.groq.com/openai/v1"
    assert cfg.llm.limits["groq_primary"].rpm == 0
    assert cfg.notifications.toast is True
    assert cfg.google.sync_minutes == 15


def test_load_config_merges_user_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[app]\ntheme = "dark"\nstart_minimized = false\n[llm]\nactive = "gemini"\n',
        encoding="utf-8",
    )
    cfg = c.load_config()
    assert cfg.app.theme == "dark"
    assert cfg.app.start_minimized is False
    assert cfg.llm.active == "gemini"
    # Unmentioned keys keep defaults.
    assert cfg.app.timezone == "Asia/Kolkata"
    assert cfg.llm.history_messages == 8


def test_config_model_extra_ignored():
    cfg = c.Config.model_validate({"app": {"timezone": "UTC", "unknown_key": 123}})
    assert cfg.app.timezone == "UTC"

"""Tests for paths.py — data root injection via SECRETARY_DATA_ROOT."""

from pathlib import Path

import secretary.paths as p


def test_data_root_defaults_to_localappdata_secretary(monkeypatch):
    monkeypatch.delenv("SECRETARY_DATA_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")
    assert p.data_root() == Path(r"C:\Users\tester\AppData\Local\Secretary")


def test_data_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    assert p.data_root() == tmp_path


def test_derived_paths_under_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    assert p.config_path() == tmp_path / "config.toml"
    assert p.db_path() == tmp_path / "secretary.db"
    assert p.backups_dir() == tmp_path / "backups"
    assert p.logs_dir() == tmp_path / "logs"


def test_ensure_dirs_creates_subdirs(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    p.ensure_dirs()
    assert (tmp_path / "backups").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert tmp_path.is_dir()


def test_credentials_path_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRETARY_CREDENTIALS", raising=False)
    monkeypatch.setenv("SECRETARY_CREDENTIALS", str(tmp_path / "creds.json"))
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")
    monkeypatch.setattr(p.sys, "frozen", False, raising=False)
    assert p.credentials_path() == tmp_path / "creds.json"


def test_credentials_path_localappdata_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRETARY_CREDENTIALS", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "Secretary").mkdir()
    (tmp_path / "Secretary" / "credentials.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(p.sys, "frozen", False, raising=False)
    assert p.credentials_path() == tmp_path / "Secretary" / "credentials.json"


def test_credentials_path_falls_back_to_project_root(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRETARY_CREDENTIALS", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(p.sys, "frozen", False, raising=False)
    assert p.credentials_path() == Path(__file__).resolve().parents[3] / "credentials.json"


def test_credentials_path_frozen_no_project_root_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRETARY_CREDENTIALS", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "Secretary").mkdir()
    (tmp_path / "Secretary" / "credentials.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(p.sys, "frozen", True, raising=False)
    assert p.credentials_path() == tmp_path / "Secretary" / "credentials.json"


def test_credentials_path_returns_existing_first(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRETARY_CREDENTIALS", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "Secretary").mkdir()
    (tmp_path / "Secretary" / "credentials.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(p.sys, "frozen", False, raising=False)
    # Both exist; LOCALAPPDATA (higher priority) wins.
    assert p.credentials_path() == tmp_path / "Secretary" / "credentials.json"

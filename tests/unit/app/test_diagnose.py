"""Tests for diagnose.py — reports key/credential presence (never values).

Exit code semantics:
- FAIL (exit 1): Python version, config load, keyring importable,
  store connects, tzdata.
- WARN (exit 0 unless a FAIL is present): missing NVIDIA/Gemini keys,
  missing Google refresh token, missing credentials.json.
"""
from __future__ import annotations

import secretary.diagnose as d


def test_diagnose_all_ok_exit_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    creds = tmp_path / "credentials.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(d, "credential_candidates", lambda: [creds])
    monkeypatch.setattr(d, "get_secret", lambda name: "present")
    code = d.run_diagnose()
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("DIAGNOSE OK")
    assert "Google credentials present:" in out
    assert str(creds) in out
    assert "NVIDIA API key [OK]" in out
    assert "Gemini API key [OK]" in out
    assert "Google refresh token [OK]" in out


def test_diagnose_missing_optional_is_warn_exit_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    creds = tmp_path / "credentials.json"
    monkeypatch.setattr(d, "credential_candidates", lambda: [creds])
    monkeypatch.setattr(d, "get_secret", lambda name: None)
    code = d.run_diagnose()
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("DIAGNOSE OK")
    assert "Google credentials [WARN] missing" in out
    assert str(creds) in out
    assert "NVIDIA API key [WARN] missing" in out
    assert "Google refresh token [WARN] missing" in out


def test_diagnose_prints_all_paths_checked_when_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    p1 = tmp_path / "a" / "credentials.json"
    p2 = tmp_path / "b" / "credentials.json"
    monkeypatch.setattr(d, "credential_candidates", lambda: [p1, p2])
    monkeypatch.setattr(d, "get_secret", lambda name: None)
    d.run_diagnose()
    out = capsys.readouterr().out
    assert "Google credentials [WARN] missing" in out
    assert "checked:" in out
    assert str(p1) in out
    assert str(p2) in out


def test_diagnose_missing_critical_is_fail_exit_one(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    creds = tmp_path / "credentials.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(d, "credential_candidates", lambda: [creds])
    monkeypatch.setattr(d, "get_secret", lambda name: None)
    # tzdata missing -> critical FAIL (exit 1 even though optional items are present)
    def boom(name):
        raise KeyError(name)

    monkeypatch.setattr(d, "ZoneInfo", boom)
    code = d.run_diagnose()
    out = capsys.readouterr().out
    assert code == 1
    assert out.startswith("DIAGNOSE FAILED")
    assert "tzdata [FAIL]" in out
    # optional items carry [WARN] even though exit is 1
    assert "Google refresh token [WARN] missing" in out
    assert str(creds) in out


def test_diagnose_markers_used(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    creds = tmp_path / "credentials.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(d, "credential_candidates", lambda: [creds])
    monkeypatch.setattr(d, "get_secret", lambda name: "present")
    d.run_diagnose()
    out = capsys.readouterr().out
    assert "on win32 [OK]" in out
    assert "config load [OK]" in out
    assert "keyring importable [OK]" in out
    assert "store connects (WAL + foreign_keys) [OK]" in out
    assert "tzdata [OK]" in out


def test_diagnose_reports_each_key_individually(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    creds = tmp_path / "credentials.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(d, "credential_candidates", lambda: [creds])
    monkeypatch.setattr(
        d,
        "get_secret",
        lambda name: "present" if name == "llm_api_key:nvidia" else None,
    )
    code = d.run_diagnose()
    out = capsys.readouterr().out
    assert code == 0
    assert "NVIDIA API key [OK]" in out
    assert "Gemini API key [WARN] missing" in out
    assert "Google refresh token [WARN] missing" in out


def test_diagnose_warns_about_a_plaintext_token_file_without_printing_it(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(d, "credential_candidates", lambda: [tmp_path / "credentials.json"])
    monkeypatch.setattr(d, "get_secret", lambda name: "present")
    (tmp_path / "google_token.json").write_text('{"refresh_token": "SECRET-VALUE"}', encoding="utf-8")
    code = d.run_diagnose()
    out = capsys.readouterr().out
    assert code == 0
    assert "google_token.json" in out and "plaintext" in out.lower()
    assert "SECRET-VALUE" not in out


def test_diagnose_is_quiet_when_no_plaintext_token_file_exists(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(d, "credential_candidates", lambda: [tmp_path / "credentials.json"])
    monkeypatch.setattr(d, "get_secret", lambda name: "present")
    d.run_diagnose()
    assert "plaintext" not in capsys.readouterr().out.lower()

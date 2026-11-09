"""Tests for diagnose.py — reports key/credential presence (never values)."""
from __future__ import annotations

import secretary.diagnose as d


def test_diagnose_all_present_ok(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    creds = tmp_path / "credentials.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(d, "credential_candidates", lambda: [creds])
    monkeypatch.setattr(d, "get_secret", lambda name: "present")
    code = d.run_diagnose()
    out = capsys.readouterr().out
    assert code == 0
    assert "Google credentials present" in out
    assert str(creds) in out
    assert "Groq API key present" in out
    assert "Gemini API key present" in out
    assert "Google refresh token present" in out


def test_diagnose_missing_credentials_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    creds = tmp_path / "credentials.json"
    monkeypatch.setattr(d, "credential_candidates", lambda: [creds])
    monkeypatch.setattr(d, "get_secret", lambda name: None)
    code = d.run_diagnose()
    out = capsys.readouterr().out
    assert code == 1
    assert "Google credentials missing" in out
    assert str(creds) in out
    assert "Google refresh token missing" in out


def test_diagnose_prints_all_paths_checked_when_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    p1 = tmp_path / "a" / "credentials.json"
    p2 = tmp_path / "b" / "credentials.json"
    monkeypatch.setattr(d, "credential_candidates", lambda: [p1, p2])
    monkeypatch.setattr(d, "get_secret", lambda name: None)
    d.run_diagnose()
    out = capsys.readouterr().out
    assert "Google credentials missing" in out
    assert str(p1) in out
    assert str(p2) in out


def test_diagnose_reports_each_key_individually(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SECRETARY_DATA_ROOT", str(tmp_path))
    creds = tmp_path / "credentials.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(d, "credential_candidates", lambda: [creds])
    monkeypatch.setattr(d, "get_secret", lambda name: "present" if name == "llm_api_key:groq" else None)
    code = d.run_diagnose()
    out = capsys.readouterr().out
    # code == 1 because gemini + google_token are missing
    assert code == 1
    assert "Groq API key present" in out
    assert "Gemini API key missing" in out
    assert "Google refresh token missing" in out

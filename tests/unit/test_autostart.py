"""Run-key autostart (plan §10.6, Appendix E).

Value name ``Secretary`` under the Windows Run key; data ends with
``--minimized`` so the app starts hidden to the tray. winreg is faked here --
no real registry writes happen in tests.
"""

from __future__ import annotations

import sys

from secretary.autostart import RUN_KEY, VALUE_NAME, command, is_enabled, set_enabled


class _FakeWinReg:
    """In-memory HKCU Run key stand-in for winreg."""

    HKEY_CURRENT_USER = object()
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.closed = 0

    def OpenKey(self, root, subkey, reserved, access):
        if subkey != RUN_KEY:
            raise FileNotFoundError("no such key")
        return self

    def CreateKeyEx(self, root, subkey, reserved, access):
        return self

    def QueryValueEx(self, key, value_name):
        try:
            return self.values[value_name], 1  # REG_SZ
        except KeyError as exc:
            raise FileNotFoundError("no such value") from exc

    def SetValueEx(self, key, value_name, reserved, typ, data):
        self.values[value_name] = data

    def DeleteValue(self, key, value_name):
        if value_name not in self.values:
            raise FileNotFoundError("no such value")
        del self.values[value_name]

    def CloseKey(self, key):
        self.closed += 1


def _install(monkeypatch, reg: _FakeWinReg) -> None:
    monkeypatch.setattr("secretary.autostart.winreg", reg)


def test_command_quoted_exe_with_minimized():
    assert '"' in command()
    assert command().endswith(" --minimized")
    assert sys.executable in command()


def test_command_frozen_uses_exe_directly(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    try:
        assert command() == f'"{sys.executable}" --minimized'
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)


def test_is_enabled_false_without_value(monkeypatch):
    reg = _FakeWinReg()
    _install(monkeypatch, reg)
    assert not is_enabled()


def test_set_enabled_true_writes_secretary_value(monkeypatch):
    reg = _FakeWinReg()
    _install(monkeypatch, reg)
    set_enabled(True)
    assert is_enabled()
    assert reg.values[VALUE_NAME] == command()
    assert reg.values[VALUE_NAME].endswith("--minimized")


def test_set_enabled_false_removes_value(monkeypatch):
    reg = _FakeWinReg()
    _install(monkeypatch, reg)
    set_enabled(True)
    set_enabled(False)
    assert not is_enabled()
    assert VALUE_NAME not in reg.values


def test_set_enabled_false_when_absent_is_noop(monkeypatch):
    reg = _FakeWinReg()
    _install(monkeypatch, reg)
    set_enabled(False)  # must not raise
    assert not is_enabled()


def test_set_enabled_true_creates_key_when_missing(monkeypatch):
    reg = _FakeWinReg()
    _install(monkeypatch, reg)
    # OpenKey raises FileNotFoundError -> set_enabled creates the key.
    set_enabled(True)
    assert is_enabled()

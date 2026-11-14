"""Global hotkey: registration result and single-fire delivery (no real OS hotkey)."""

from __future__ import annotations

import ctypes

import secretary.hotkey as hotkey_module
from secretary.hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MSG,
    WM_HOTKEY,
    GlobalHotkey,
    HotkeyFilter,
)


class _FakeUser32:
    def __init__(self, ok: bool) -> None:
        self.ok = ok
        self.calls: list[tuple] = []

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, vk):
        self.calls.append((hwnd, hotkey_id, modifiers, vk))
        return 1 if self.ok else 0


def _message(wparam: int) -> int:
    msg = MSG()
    msg.message = WM_HOTKEY
    msg.wParam = wparam
    _message.keep = msg  # keep alive while the pointer is used
    return ctypes.addressof(msg)


def test_registers_ctrl_alt_space_for_calling_thread(monkeypatch):
    fake = _FakeUser32(ok=True)
    monkeypatch.setattr(hotkey_module, "_user32", lambda: fake)
    hk = GlobalHotkey(MOD_ALT | MOD_CONTROL, 0x20, lambda: None)
    assert hk.registered
    hwnd, _id, mods, vk = fake.calls[0]
    assert hwnd is None and vk == 0x20
    assert mods == MOD_ALT | MOD_CONTROL | MOD_NOREPEAT


def test_failed_registration_is_not_fatal(monkeypatch):
    monkeypatch.setattr(hotkey_module, "_user32", lambda: _FakeUser32(ok=False))
    hk = GlobalHotkey(MOD_ALT | MOD_CONTROL, 0x20, lambda: None)
    assert hk.registered is False
    assert HotkeyFilter(hk).nativeEventFilter(b"windows_generic_MSG", _message(hk.id))[0] is False


def test_hotkey_press_fires_callback_exactly_once(monkeypatch):
    monkeypatch.setattr(hotkey_module, "_user32", lambda: _FakeUser32(ok=True))
    fired: list[int] = []
    hk = GlobalHotkey(MOD_ALT | MOD_CONTROL, 0x20, lambda: fired.append(1))
    flt = HotkeyFilter(hk)
    assert flt.nativeEventFilter(b"windows_generic_MSG", _message(hk.id))[0] is True
    assert fired == [1]
    # A different hotkey id or message type is ignored.
    assert flt.nativeEventFilter(b"windows_generic_MSG", _message(hk.id + 1))[0] is False
    assert fired == [1]

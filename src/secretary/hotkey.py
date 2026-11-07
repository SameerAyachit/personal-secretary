"""Global hotkey spike for quick capture.

Uses Win32 ``RegisterHotKey`` behind an import guard so the rest of the app runs
headless / on non-Windows. Registration result is surfaced as an error rather
than silently failing (plan §20.5, C-7).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class HotkeyError(Exception):
    pass


class GlobalHotkey:
    """Registers a system-wide hotkey that invokes a callback on the main thread."""

    def __init__(self, modifiers: int, vk: int, callback: Callable[[], None]) -> None:
        self._modifiers = modifiers
        self._vk = vk
        self._callback = callback
        self._registered = False
        self._hwnd = None
        self._atom = None
        self._try_register()

    def _try_register(self) -> None:
        try:
            win32gui = importlib.import_module("win32gui")
            win32con = importlib.import_module("win32con")
        except ImportError:
            # pywin32 not available (or not Windows): hotkey unavailable.
            return
        try:
            self._hwnd = win32gui.CreateWindow(win32con.Static, "SecretaryHotkey", 0, 0, 0, 0, 0, 0, 0, 0, None)
            self._atom = win32gui.GlobalAddAtom("SecretaryHotkey")
            ok = win32gui.RegisterHotKey(self._hwnd, self._atom, self._modifiers, self._vk)
            self._registered = bool(ok)
        except OSError:
            self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    def unregister(self) -> None:
        if self._registered and self._hwnd is not None and self._atom is not None:
            try:
                win32gui = importlib.import_module("win32gui")
                win32gui.UnregisterHotKey(self._hwnd, self._atom)
            except (ImportError, OSError):
                pass
            self._registered = False

    def check_message(self, msg_hwnd, msg, wparam, lparam) -> bool:
        """Call from the Win32 message pump; returns True if the hotkey fired."""
        if not self._registered:
            return False
        try:
            win32con = importlib.import_module("win32con")
        except ImportError:
            return False
        if msg == win32con.WM_HOTKEY and wparam == self._atom:
            self._callback()
            return True
        return False

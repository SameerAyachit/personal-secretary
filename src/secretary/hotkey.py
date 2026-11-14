"""Global hotkey for quick capture via Win32 ``RegisterHotKey`` (plan §20.5, C-7).

Pure ``ctypes`` (no pywin32). The hotkey is registered for the calling thread
(the GUI thread, ``hWnd=NULL``); Windows then posts ``WM_HOTKEY`` to that
thread's queue, where :class:`HotkeyFilter` sees it through Qt's native event
filter. A failed registration (for example another app owns the combination)
is logged, never raised, so the rest of the app keeps running.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

logger = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
_HOTKEY_ID = 0x5EC1


_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "meta": MOD_WIN,
    "super": MOD_WIN,
}
_NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B}
DEFAULT_HOTKEY = "Ctrl+Alt+Space"


def parse_hotkey(text: str) -> tuple[int, int]:
    """``"Ctrl+Alt+Space"`` -> ``(modifier flags, virtual-key code)``.

    Needs at least one modifier and exactly one key (a letter, digit, F1-F24 or
    Space/Enter/Tab/Esc). Raises ``ValueError`` otherwise.
    """
    parts = [p.strip().lower() for p in text.split("+")]
    if len(parts) < 2 or any(not p for p in parts):
        raise ValueError(f"invalid hotkey {text!r}: expected e.g. 'Ctrl+Alt+Space'")
    modifiers = 0
    keys: list[int] = []
    for part in parts:
        if part in _MODIFIERS:
            modifiers |= _MODIFIERS[part]
        elif part in _NAMED_KEYS:
            keys.append(_NAMED_KEYS[part])
        elif len(part) == 1 and part.isalnum() and part.isascii():
            keys.append(ord(part.upper()))
        elif part[0] == "f" and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            keys.append(0x70 + int(part[1:]) - 1)
        else:
            raise ValueError(f"invalid hotkey {text!r}: unknown key {part!r}")
    if not modifiers or len(keys) != 1:
        raise ValueError(f"invalid hotkey {text!r}: need at least one modifier and exactly one key")
    return modifiers, keys[0]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def _user32():
    """The user32 DLL, or None off Windows. Separate function so tests can fake it."""
    return ctypes.windll.user32 if sys.platform == "win32" else None


class GlobalHotkey:
    """Registers a system-wide hotkey; :class:`HotkeyFilter` delivers the press."""

    def __init__(self, modifiers: int, vk: int, callback: Callable[[], None]) -> None:
        self.id = _HOTKEY_ID
        self.callback = callback
        self.registered = False
        user32 = _user32()
        if user32 is None:
            return
        self.registered = bool(user32.RegisterHotKey(None, self.id, modifiers | MOD_NOREPEAT, vk))
        if not self.registered:
            logger.warning(
                "global hotkey registration failed (winerror=%s); the combination may be in use",
                ctypes.GetLastError(),
            )


class HotkeyFilter(QAbstractNativeEventFilter):
    """Qt native event filter that turns ``WM_HOTKEY`` into one callback call."""

    def __init__(self, hotkey: GlobalHotkey) -> None:
        super().__init__()
        self._hotkey = hotkey

    def nativeEventFilter(self, eventType, message):  # type: ignore[override]
        if eventType == b"windows_generic_MSG" and self._hotkey.registered:
            msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey.id:
                self._hotkey.callback()
                return True, 0
        return False, 0

"""Windows Run-key autostart (plan §10.6, Appendix E).

Value name ``Secretary`` under
``HKCU\Software\Microsoft\Windows\CurrentVersion\Run``; data is the login
command with ``--minimized`` so the app starts hidden to the tray. Settings
reads this key to show the true state and adds/removes the value.
"""

from __future__ import annotations

import contextlib
import sys

if sys.platform == "win32":  # pragma: no cover - Windows only
    import winreg
else:  # pragma: no cover - Windows only
    winreg = None  # type: ignore[assignment]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Secretary"


def command() -> str:
    """Command launched at login.

    Packaged (PyInstaller): ``secretary.exe --minimized`` — matches
    ``packaging/installer.iss``. Dev: ``python -m secretary --minimized``.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    return f'"{sys.executable}" -m secretary --minimized'


def is_enabled() -> bool:
    """True if the Run-key value exists (the source of truth for autostart)."""
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE
        )
    except FileNotFoundError:
        return False
    try:
        winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    finally:
        winreg.CloseKey(key)


def set_enabled(enabled: bool) -> None:
    """Add or remove the Run-key value."""
    if winreg is None:
        return
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
    except FileNotFoundError:
        key = None
    try:
        if key is None:
            if not enabled:
                return
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            )
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, VALUE_NAME)
    finally:
        if key is not None:
            winreg.CloseKey(key)

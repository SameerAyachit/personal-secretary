"""UI theme: design tokens and generated QSS."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from .qss import apply_theme, generate_qss
from .tokens import DARK, LIGHT, Palette, Tokens, tokens

__all__ = ["DARK", "LIGHT", "Palette", "Tokens", "apply_theme", "generate_qss", "resolve_theme", "tokens"]


def resolve_theme(stored: str) -> str:
    """Resolve the stored theme; ``"system"`` follows the Windows color scheme."""
    if stored != "system":
        return stored
    scheme = QGuiApplication.styleHints().colorScheme()
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"

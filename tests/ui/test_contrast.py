"""Contrast ratios computed from design tokens, both themes (skill §4)."""
from __future__ import annotations

from secretary.ui.theme import DARK, LIGHT


def _luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    rgb = [int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in rgb
    ]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(fg: str, bg: str) -> float:
    la, lb = _luminance(fg), _luminance(bg)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _check(theme_name: str, palette, pairs: list[tuple[str, str, str]]) -> None:
    for label, fg_attr, bg_attr in pairs:
        ratio = _ratio(getattr(palette, fg_attr), getattr(palette, bg_attr))
        assert ratio >= 4.5, f"{theme_name} {label}: {ratio:.2f} < 4.5:1"


PAIRS = [("text on bg", "text", "bg"), ("text_muted on bg", "text_muted", "bg"), ("accent_text on accent", "accent_text", "accent")]


def test_light_theme_contrast() -> None:
    _check("light", LIGHT, PAIRS)


def test_dark_theme_contrast() -> None:
    _check("dark", DARK, PAIRS)

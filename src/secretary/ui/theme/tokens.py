"""Design tokens for the Secretary UI (plan §12.4, secretary-ui-design skill).

All semantic colors and spacing live here. QSS is GENERATED from these tokens
(see theme.qss_generator), never hand-edited with raw hex in widgets.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_text: str
    danger: str
    success: str
    warning: str
    focus: str


# Starting palettes (adjust only to hit contrast >= 4.5:1 text / >= 3:1 icons).
LIGHT = Palette(
    bg="#F5F6F8",
    surface="#FFFFFF",
    surface_alt="#EEF0F3",
    border="#D9DDE3",
    text="#1B1F24",
    text_muted="#5B6573",
    accent="#2F6FED",
    accent_text="#FFFFFF",
    danger="#C62828",
    success="#1E7A3C",
    warning="#9A6700",
    focus="#2F6FED",
)

DARK = Palette(
    bg="#14171B",
    surface="#1C2026",
    surface_alt="#242A31",
    border="#323A44",
    text="#E8ECF1",
    text_muted="#9AA6B5",
    accent="#6EA2FF",
    accent_text="#0B1220",
    danger="#FF6B6B",
    success="#4CC26F",
    warning="#E3B341",
    focus="#6EA2FF",
)


@dataclass(frozen=True)
class Tokens:
    palette: Palette
    # Spacing (only these values may be used): 4 / 8 / 12 / 16 / 24.
    space_xs: int = 4
    space_sm: int = 8
    space_md: int = 12
    space_lg: int = 16
    space_xl: int = 24
    # Radii: 6 (controls), 10 (cards), 999 (chips).
    radius_control: int = 6
    radius_card: int = 10
    radius_chip: int = 999
    # Layout.
    window_margin: int = 16
    card_padding: int = 12
    card_padding_wide: int = 16
    row_height: int = 36
    rail_width: int = 200
    min_window_width: int = 900
    min_window_height: int = 600
    # Type (pt-equivalent).
    size_title: int = 20
    size_section: int = 15
    size_body: int = 13
    size_caption: int = 11
    focus_ring_width: int = 2
    focus_ring_offset: int = 1


def tokens(theme: str = "light") -> Tokens:
    palette = LIGHT if theme == "light" else DARK
    return Tokens(palette=palette)

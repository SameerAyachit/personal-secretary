"""QSS generation from design tokens (plan §12.4, secretary-ui-design skill).

QSS is GENERATED from tokens; widgets never contain raw hex colors.
"""

from __future__ import annotations

from .tokens import Tokens, tokens


def _focus(palette) -> str:
    return f"2px solid {palette.focus}"


def generate_qss(tokens: Tokens) -> str:
    p = tokens.palette
    t = tokens
    return f"""
/* ===== Secretary theme (generated from tokens; do not hand-edit) ===== */
QWidget {{
    background-color: {p.bg};
    color: {p.text};
    font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
    font-size: {t.size_body}pt;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QMainWindow {{
    background-color: {p.bg};
}}
QFrame#Card {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {t.radius_card}px;
}}
QFrame#Card[surface_alt="true"] {{
    background-color: {p.surface_alt};
}}
QPushButton {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {t.radius_control}px;
    padding: {t.space_sm}px {t.space_md}px;
    min-height: {t.row_height}px;
    color: {p.text};
}}
QPushButton:hover {{
    background-color: {p.border};
}}
QPushButton:pressed {{
    background-color: {p.text_muted};
}}
QPushButton#Accent {{
    background-color: {p.accent};
    color: {p.accent_text};
    border: none;
}}
QPushButton#Accent:hover {{
    background-color: {p.focus};
}}
QPushButton#Danger {{
    background-color: {p.danger};
    color: #FFFFFF;
    border: none;
}}
QPushButton#Danger:hover {{
    background-color: #A11E1E;
}}
QPushButton:focus {{
    outline: none;
    border: {_focus(p)};
    border-radius: {t.radius_control}px;
}}
QLineEdit, QPlainTextEdit {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {t.radius_control}px;
    padding: {t.space_sm}px {t.space_md}px;
    min-height: {t.row_height}px;
    color: {p.text};
}}
QLineEdit:focus, QPlainTextEdit:focus {{
    border: {_focus(p)};
}}
QListView, QListWidget {{
    background-color: {p.bg};
    border: none;
    outline: none;
    show-decoration-selected: 1;
}}
QListView::item, QListWidget::item {{
    background-color: transparent;
    border: none;
    padding: {t.space_xs}px {t.space_md}px;
    min-height: {t.row_height}px;
    color: {p.text};
}}
QListView::item:selected, QListWidget::item:selected {{
    background-color: {p.accent};
    color: {p.accent_text};
    border-radius: {t.radius_control}px;
}}
QListView::item:hover:!selected, QListWidget::item:hover:!selected {{
    background-color: {p.surface_alt};
}}
QLabel#Title {{
    font-size: {t.size_title}pt;
    font-weight: 600;
    color: {p.text};
}}
QLabel#Section {{
    font-size: {t.size_section}pt;
    font-weight: 600;
    color: {p.text};
}}
QLabel#Body {{
    font-size: {t.size_body}pt;
    color: {p.text};
}}
QLabel#Caption {{
    font-size: {t.size_caption}pt;
    color: {p.text_muted};
}}
QLabel#Muted {{
    color: {p.text_muted};
}}
QLabel[newRecipient="true"] {{
    font-weight: 600;
    color: {p.warning};
}}
QToolTip {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    color: {p.text};
    font-size: {t.size_caption}pt;
}}
QScrollBar:vertical {{
    background: {p.bg};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.border};
    border-radius: 5px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.text_muted};
}}
"""


def apply_theme(app, theme: str = "light") -> None:
    tokens_obj = tokens(theme)
    app.setStyleSheet(generate_qss(tokens_obj))

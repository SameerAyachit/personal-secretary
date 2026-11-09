"""Settings view (plan §12.2).

General page: timezone/startup read from the controller. The "Start at login"
checkbox is the Settings autostart toggle (plan §10.6, Appendix E): it adds or
removes the ``Secretary`` value under the HKCU Run key; the checkbox always
shows the true state read from that key.
"""

from __future__ import annotations

import contextlib

from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QVBoxLayout, QWidget

from secretary.controller import Controller
from secretary.ui.theme import tokens


class SettingsView(QWidget):
    """Settings view: General page with the start-at-login autostart toggle."""

    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self._controller = controller
        self._tokens = tokens("light")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            self._tokens.space_lg, self._tokens.space_lg,
            self._tokens.space_lg, self._tokens.space_lg,
        )
        layout.setSpacing(self._tokens.space_md)

        title = QLabel("Settings")
        title.setObjectName("Section")
        layout.addWidget(title)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            self._tokens.card_padding_wide, self._tokens.card_padding_wide,
            self._tokens.card_padding_wide, self._tokens.card_padding_wide,
        )
        card_layout.setSpacing(self._tokens.space_sm)

        section = QLabel("General")
        section.setObjectName("Section")
        card_layout.addWidget(section)

        self._autostart = QCheckBox("Start Secretary at login")
        self._autostart.setAccessibleName("Start at login")
        self._autostart.setToolTip(
            "Start Secretary hidden to the tray when you log in "
            "(writes the value to the Windows Run key)."
        )
        self._autostart.setChecked(self._controller.get_autostart())
        self._autostart.toggled.connect(self._on_autostart_toggled)
        card_layout.addWidget(self._autostart)

        card_layout.addStretch()
        layout.addWidget(card)
        layout.addStretch()

    def refresh_autostart(self) -> None:
        """Re-read the Run key so the checkbox shows the true state."""
        with contextlib.suppress(Exception):
            self._autostart.setChecked(self._controller.get_autostart())

    def _on_autostart_toggled(self, checked: bool) -> None:
        try:
            self._controller.set_autostart(checked)
        except Exception:
            # Revert the checkbox if the Run key cannot be written.
            self._autostart.blockSignals(True)
            self._autostart.setChecked(not checked)
            self._autostart.blockSignals(False)

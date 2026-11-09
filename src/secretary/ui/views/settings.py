"""Settings view (plan §12.2).

General page: theme and startup read from the controller. The "Start at login"
checkbox is the Settings autostart toggle (plan §10.6, Appendix E): it adds or
removes the ``Secretary`` value under the HKCU Run key; the checkbox always
shows the true state read from that key.
"""

from __future__ import annotations

import contextlib
import io

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from secretary.controller import Controller
from secretary.diagnose import run_diagnose
from secretary.ui.theme import tokens


class SettingsView(QWidget):
    """Settings view: General page with theme and start-at-login autostart."""

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

        self._theme = QComboBox()
        self._theme.setAccessibleName("Theme")
        self._theme.addItems(["System", "Light", "Dark"])
        self._theme.setCurrentText(
            {"light": "Light", "dark": "Dark"}.get(
                self._controller.get_config().get("theme", "light"), "System"
            )
        )
        self._theme.currentTextChanged.connect(self._on_theme_changed)
        card_layout.addWidget(self._theme)

        self._autostart = QCheckBox("Start Secretary at login")
        self._autostart.setAccessibleName("Start at login")
        self._autostart.setToolTip(
            "Start Secretary hidden to the tray when you log in "
            "(writes the value to the Windows Run key)."
        )
        self._autostart.setChecked(self._controller.get_autostart())
        self._autostart.toggled.connect(self._on_autostart_toggled)
        card_layout.addWidget(self._autostart)

        # ---- Google -------------------------------------------------------
        section = QLabel("Google Calendar & Gmail")
        section.setObjectName("Section")
        card_layout.addWidget(section)

        self._google_status = QLabel()
        self._google_status.setObjectName("Caption")
        card_layout.addWidget(self._google_status)

        self._google_button = QPushButton("Connect Google")
        self._google_button.setAccessibleName("Connect Google")
        self._google_button.clicked.connect(self._on_connect_google)
        card_layout.addWidget(self._google_button)

        self._controller.google_connected.connect(self.refresh_google)
        self.refresh_google()

        card_layout.addStretch()
        layout.addWidget(card)
        layout.addStretch()

    def refresh_google(self) -> None:
        """Re-read the refresh-token state and update the button/status."""
        try:
            connected = self._controller.get_google_connected()
        except Exception:
            connected = False
        self._google_status.setText(
            "Google: connected"
            if connected
            else "Google: not connected (click Connect Google)"
        )
        self._google_button.setText("Reconnect Google" if connected else "Connect Google")
        self._google_button.setAccessibleName(
            "Reconnect Google" if connected else "Connect Google"
        )

    def _on_connect_google(self) -> None:
        try:
            self._controller.connect_google()
        except Exception as exc:  # surface to the diagnostics-style error
            self._google_status.setText(f"Google: connect failed ({exc})")

    def _run_diagnostics(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = run_diagnose()
        title = "Diagnostics — OK" if code == 0 else "Diagnostics — problems found"
        QMessageBox.information(self, title, buf.getvalue() or "(no output)")

    def refresh_autostart(self) -> None:
        """Re-read the Run key so the checkbox shows the true state."""
        with contextlib.suppress(Exception):
            self._autostart.setChecked(self._controller.get_autostart())

    def _on_theme_changed(self, text: str) -> None:
        mapping = {"System": "system", "Light": "light", "Dark": "dark"}
        try:
            self._controller.set_theme(mapping[text])
        except Exception:
            self._theme.blockSignals(True)
            self._theme.setCurrentText(
                {"system": "System", "light": "Light", "dark": "Dark"}.get(
                    self._controller.get_config().get("theme", "light"), "System"
                )
            )
            self._theme.blockSignals(False)

    def _on_autostart_toggled(self, checked: bool) -> None:
        try:
            self._controller.set_autostart(checked)
        except Exception:
            # Revert the checkbox if the Run key cannot be written.
            self._autostart.blockSignals(True)
            self._autostart.setChecked(not checked)
            self._autostart.blockSignals(False)

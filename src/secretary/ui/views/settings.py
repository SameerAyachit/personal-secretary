"""Settings view (plan §12.2).

General page: theme and startup read from the controller. The "Start at login"
checkbox is the Settings autostart toggle (plan §10.6, Appendix E): it adds or
removes the ``Secretary`` value under the HKCU Run key; the checkbox always
shows the true state read from that key.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from secretary.controller import Controller
from secretary.diagnose import run_diagnose
from secretary.ui.theme import apply_theme, resolve_theme, tokens


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

        self._sync_status = QLabel()
        self._sync_status.setObjectName("Caption")
        card_layout.addWidget(self._sync_status)

        self._controller.google_connected.connect(self.refresh_google)
        self._controller.error.connect(self._on_controller_error)
        self.refresh_google()

        # ---- Data -----------------------------------------------------------
        section = QLabel("Data")
        section.setObjectName("Section")
        card_layout.addWidget(section)

        self._last_backup = QLabel()
        self._last_backup.setObjectName("Caption")
        card_layout.addWidget(self._last_backup)
        self.refresh_backups()

        btn_backup = QPushButton("Backup now")
        btn_backup.setAccessibleName("Backup now")
        btn_backup.clicked.connect(self._on_backup_now)
        card_layout.addWidget(btn_backup)

        row = QHBoxLayout()
        btn_restore = QPushButton("Restore from backup…")
        btn_restore.setAccessibleName("Restore from backup")
        btn_restore.clicked.connect(self._on_restore_backup)
        row.addWidget(btn_restore)
        btn_delete = QPushButton("Delete all data")
        btn_delete.setAccessibleName("Delete all data")
        btn_delete.setObjectName("Danger")
        btn_delete.clicked.connect(self._on_delete_all_data)
        row.addWidget(btn_delete)
        card_layout.addLayout(row)

        row = QHBoxLayout()
        btn_export_json = QPushButton("Export JSON")
        btn_export_json.setAccessibleName("Export JSON")
        btn_export_json.clicked.connect(lambda: self._on_export("json"))
        row.addWidget(btn_export_json)
        btn_export_md = QPushButton("Export Markdown")
        btn_export_md.setAccessibleName("Export Markdown")
        btn_export_md.clicked.connect(lambda: self._on_export("markdown"))
        row.addWidget(btn_export_md)
        card_layout.addLayout(row)

        card_layout.addStretch()
        layout.addWidget(card)
        layout.addStretch()

    def refresh_backups(self) -> None:
        """Show the newest backup (Settings Data page)."""
        try:
            backups = self._controller.list_backups()
        except Exception:
            backups = []
        if backups:
            latest = backups[0]
            self._last_backup.setText(
                f"Last backup: {latest['name']} ({latest['size']} bytes)"
            )
        else:
            self._last_backup.setText("No backups yet.")

    @Slot()
    def _on_backup_now(self) -> None:
        try:
            result = self._controller.backup_now()
            if result:
                self.refresh_backups()
                self._last_backup.setText(
                    f"Backed up: {result['name']} ({result.get('size', 0)} bytes)"
                )
        except Exception as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))

    @Slot()
    def _on_restore_backup(self) -> None:
        backups = self._controller.list_backups()
        if not backups:
            QMessageBox.information(self, "Restore", "No backups available.")
            return
        name, ok = QFileDialog.getOpenFileName(
            self,
            "Restore from backup",
            str(Path(backups[0]["path"]).parent),
            "Secretary backup (*.db)",
        )
        if not ok or not name:
            return
        confirm = QMessageBox.question(
            self,
            "Restore backup",
            f"Replace current data with '{Path(name).name}'?\n"
            "A safety copy of the current DB is kept and the app restarts.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._controller.restore_backup(Path(name).name)
        except Exception as exc:
            QMessageBox.warning(self, "Restore failed", str(exc))

    @Slot()
    def _on_delete_all_data(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Delete all data",
            "This permanently wipes the database, backups, logs and saved "
            "credentials, then quits the app. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._controller.delete_all_data()
        except Exception as exc:
            QMessageBox.warning(self, "Delete all data failed", str(exc))

    @Slot()
    def _on_export(self, fmt: str) -> None:
        try:
            result = self._controller.export_data(fmt)
            QMessageBox.information(
                self, "Export complete", f"Exported to {result['name']}"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

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
        sync = self._controller.get_google_sync_status()
        if sync.get("failed"):
            self._sync_status.setText(f"Google sync: failed ({sync.get('error', '')})")
        else:
            self._sync_status.setText("Google sync: OK")

    def _on_connect_google(self) -> None:
        try:
            self._controller.connect_google()
        except Exception as exc:  # surface to the diagnostics-style error
            self._google_status.setText(f"Google: connect failed ({exc})")

    @Slot(str, str)
    def _on_controller_error(self, action: str, message: str) -> None:
        if action == "google_connect":
            self._google_status.setText(f"Google: connect failed ({message})")

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
        theme = mapping[text]
        try:
            self._controller.set_theme(theme)
        except Exception:
            self._theme.blockSignals(True)
            self._theme.setCurrentText(
                {"system": "System", "light": "Light", "dark": "Dark"}.get(
                    self._controller.get_config().get("theme", "light"), "System"
                )
            )
            self._theme.blockSignals(False)
            return
        # Regenerate and re-apply the QSS so the change takes effect immediately.
        apply_theme(QApplication.instance(), resolve_theme(theme))

    def _on_autostart_toggled(self, checked: bool) -> None:
        try:
            self._controller.set_autostart(checked)
        except Exception:
            # Revert the checkbox if the Run key cannot be written.
            self._autostart.blockSignals(True)
            self._autostart.setChecked(not checked)
            self._autostart.blockSignals(False)

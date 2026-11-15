"""Settings view (plan §12.2).

Four tabs only:
  * General: theme and start-at-login autostart.
  * AI: LLM provider, model, API key field, Test connection.
  * Google: Connect/Reconnect, status, last sync, one error line.
  * Data: backup now, restore from backup, export JSON/Markdown, delete all data.

Everything else (for example memory facts) lives in the Diagnostics view, not
here. Secret values are never echoed back to the screen.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from secretary.controller import Controller
from secretary.ui.theme import apply_theme, resolve_theme, tokens


class SettingsView(QWidget):
    """Settings view: four tabs (General, AI, Google, Data)."""

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

        self._ai_models_requested = False
        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._ai_tab(), "AI")
        tabs.addTab(self._google_tab(), "Google")
        tabs.addTab(self._data_tab(), "Data")
        layout.addWidget(tabs)
        tabs.currentChanged.connect(self._on_tab_changed)

        self._controller.error.connect(self._on_controller_error)
        self._controller.models_loaded.connect(self._on_models_loaded)
        self._controller.connection_tested.connect(self._on_connection_tested)
        self.refresh_google()

    # ------------------------------------------------------------------ General

    def _general_tab(self) -> QWidget:
        card = QGroupBox("General")
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setSpacing(12)

        self._theme = QComboBox()
        self._theme.setAccessibleName("Theme")
        self._theme.addItems(["System", "Light", "Dark"])
        self._theme.setCurrentText(
            {"light": "Light", "dark": "Dark"}.get(
                self._controller.get_config().get("theme", "light"), "System"
            )
        )
        self._theme.currentTextChanged.connect(self._on_theme_changed)
        grid.addWidget(QLabel("Theme"), 0, 0)
        grid.addWidget(self._theme, 0, 1)

        self._autostart = QCheckBox("Start Secretary at login")
        self._autostart.setAccessibleName("Start at login")
        self._autostart.setToolTip(
            "Start Secretary hidden to the tray when you log in "
            "(writes the value to the Windows Run key)."
        )
        self._autostart.setChecked(self._controller.get_autostart())
        self._autostart.toggled.connect(self._on_autostart_toggled)
        grid.addWidget(self._autostart, 1, 0, 1, 2)
        return card

    # ------------------------------------------------------------------ AI

    def _ai_tab(self) -> QWidget:
        card = QGroupBox("AI")
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setSpacing(10)

        llm = self._controller.get_llm_config()
        provider = llm["active"]
        providers = list(llm["providers"].keys())

        self._ai_provider = QComboBox()
        self._ai_provider.setAccessibleName("LLM provider")
        self._ai_provider.addItems(providers)
        if provider in providers:
            self._ai_provider.setCurrentText(provider)
        self._ai_provider.currentTextChanged.connect(self._on_ai_provider_changed)
        grid.addWidget(QLabel("Provider"), 0, 0)
        grid.addWidget(self._ai_provider, 0, 1)

        self._ai_model = QComboBox()
        self._ai_model.setAccessibleName("Model")
        self._ai_model.setEditable(True)
        # Long model ids must not widen the whole page (it overflowed at 125% text).
        self._ai_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._ai_model.setMinimumContentsLength(24)
        self._ai_provider.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._ai_provider.setMinimumContentsLength(12)
        grid.addWidget(QLabel("Model"), 1, 0)
        grid.addWidget(self._ai_model, 1, 1)
        # The dropdown is usable straight away with the configured model; the
        # provider's full list is requested lazily (first time the AI tab opens,
        # or when the provider changes) so building the view never makes a
        # network call (plan B9).
        configured = llm["providers"].get(provider, {}).get("model", "")
        if configured:
            self._ai_model.addItem(configured)

        self._ai_key = QLineEdit()
        self._ai_key.setAccessibleName("API key")
        self._ai_key.setPlaceholderText("API key (hidden)")
        self._ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(QLabel("API key"), 2, 0)
        grid.addWidget(self._ai_key, 2, 1)

        self._ai_key_status = QLabel()
        self._ai_key_status.setObjectName("Caption")
        grid.addWidget(self._ai_key_status, 3, 0, 1, 2)
        self._refresh_ai_key_status()

        btn_test = QPushButton("Test connection")
        btn_test.setAccessibleName("Test LLM connection")
        btn_test.clicked.connect(self._on_ai_test)
        grid.addWidget(btn_test, 4, 0)

        self._ai_status = QLabel()
        self._ai_status.setObjectName("Caption")
        self._ai_status.setHidden(True)
        grid.addWidget(self._ai_status, 4, 1)

        btn_save = QPushButton("Save provider")
        btn_save.setAccessibleName("Save LLM provider")
        btn_save.clicked.connect(self._on_ai_save)
        grid.addWidget(btn_save, 5, 0)

        return card

    def _on_tab_changed(self, index: int) -> None:
        """Request the model list the first time the AI tab is opened."""
        if index == 1 and not self._ai_models_requested:
            self._refresh_ai_models()

    def _on_ai_provider_changed(self, text: str) -> None:
        self._refresh_ai_models()
        self._refresh_ai_key_status()

    def _refresh_ai_models(self) -> None:
        """Request the provider's models on the worker loop (plan B9).

        The dropdown stays usable while the list loads; results arrive via the
        models_loaded signal and never replace the model you picked.
        """
        self._ai_models_requested = True
        provider = self._ai_provider.currentText()
        # Switching provider: show that provider's configured model meanwhile.
        configured = self._controller.get_llm_config()["providers"].get(provider, {}).get("model", "")
        self._ai_model.blockSignals(True)
        self._ai_model.clear()
        if configured:
            self._ai_model.addItem(configured)
        self._ai_model.setEnabled(True)
        self._ai_model.blockSignals(False)
        self._controller.get_available_models(provider)

    def _on_models_loaded(self, provider: str, models: list[str]) -> None:
        """Fill the dropdown with the provider's models, keeping the current choice."""
        if provider != self._ai_provider.currentText():
            return  # stale result from a previous provider selection
        configured = self._controller.get_llm_config()["providers"][provider]["model"] or ""
        wanted = self._ai_model.currentText().strip() or configured
        self._ai_model.blockSignals(True)
        if models:
            self._ai_model.clear()
            self._ai_model.addItems(models)
        if wanted and self._ai_model.findText(wanted) < 0:
            self._ai_model.addItem(wanted)
        self._ai_model.setCurrentText(wanted)
        self._ai_model.setEnabled(True)
        self._ai_model.blockSignals(False)

    def _refresh_ai_key_status(self) -> None:
        """Show key status (saved / missing / placeholder), never the value."""
        status = self._controller.get_llm_key_status()
        label = {
            "missing": "API key: missing",
            "placeholder": "API key: looks like a placeholder, please re-enter it",
            "saved": "API key: saved",
        }.get(status["status"], f"API key: {status['status']}")
        self._ai_key_status.setText(label)
        self._ai_key_status.setHidden(False)

    def _on_ai_test(self) -> None:
        provider = self._ai_provider.currentText()
        prov = self._controller.get_llm_config()["providers"][provider]
        self._ai_status.setText("Testing connection…")
        self._ai_status.setHidden(False)
        # Runs on the worker loop; result arrives via connection_tested signal.
        self._controller.test_llm_connection(
            prov["base_url"], self._ai_key.text(), self._ai_model.currentText()
        )

    def _on_connection_tested(self, provider: str, result: dict) -> None:
        """Show the test connection result on the Google/AI tab."""
        if provider != self._ai_provider.currentText():
            return  # stale result from a previous provider selection
        if "error" in result:
            self._ai_status.setText(f"Test failed: {result['error']}")
        else:
            self._ai_status.setText("Test connection OK")
        self._ai_status.setHidden(False)

    def _on_ai_save(self) -> None:
        try:
            prov = self._controller.get_llm_config()["providers"][self._ai_provider.currentText()]
            self._controller.set_llm_provider(
                self._ai_provider.currentText(),
                self._ai_key.text(),
                prov["base_url"],
                self._ai_model.currentText(),
            )
            self._ai_status.setText("Provider saved")
            self._ai_status.setHidden(False)
            self._refresh_ai_key_status()
        except Exception as exc:  # surface exact error, never secrets
            self._ai_status.setText(f"Save failed: {exc}")
            self._ai_status.setHidden(False)

    # ------------------------------------------------------------------ Google

    def _google_tab(self) -> QWidget:
        card = QGroupBox("Google Calendar & Gmail")
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setSpacing(10)

        self._google_status = QLabel()
        self._google_status.setObjectName("Caption")
        grid.addWidget(self._google_status, 0, 0, 1, 2)

        self._sync_status = QLabel()
        self._sync_status.setObjectName("Caption")
        grid.addWidget(self._sync_status, 1, 0, 1, 2)

        self._google_button = QPushButton("Connect Google")
        self._google_button.setAccessibleName("Connect Google")
        self._google_button.clicked.connect(self._on_connect_google)
        grid.addWidget(self._google_button, 2, 0)

        self._google_disconnect = QPushButton("Disconnect")
        self._google_disconnect.setAccessibleName("Disconnect Google")
        self._google_disconnect.clicked.connect(self._on_disconnect_google)
        grid.addWidget(self._google_disconnect, 2, 1)

        self._google_reconnect = QPushButton("Reconnect Google")
        self._google_reconnect.setAccessibleName("Reconnect Google")
        self._google_reconnect.clicked.connect(self._on_connect_google)
        grid.addWidget(self._google_reconnect, 2, 2)
        self._google_reconnect.setVisible(False)

        self._google_error = QLabel()
        self._google_error.setObjectName("Caption")
        self._google_error.setHidden(True)
        grid.addWidget(self._google_error, 3, 0, 1, 2)

        self._controller.google_connected.connect(self.refresh_google)
        self._controller.error.connect(self._on_controller_error)
        return card

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
        self._google_button.setVisible(not connected)
        self._google_button.setText("Connect Google")
        self._google_button.setAccessibleName("Connect Google")
        self._google_button.setEnabled(not connected)
        self._google_disconnect.setVisible(connected)
        self._google_disconnect.setEnabled(connected)
        self._google_reconnect.setVisible(connected)
        self._google_reconnect.setEnabled(connected)
        sync = self._controller.get_google_sync_status()
        if sync.get("failed"):
            self._sync_status.setText(f"Google sync: failed ({sync.get('error', '')})")
        else:
            self._sync_status.setText("Google sync: OK")

    @Slot()
    def _on_connect_google(self) -> None:
        try:
            self._controller.connect_google()
        except Exception as exc:  # surface to the Google tab
            self._google_error.setText(f"Connect failed: {exc}")
            self._google_error.setHidden(False)

    @Slot()
    def _on_disconnect_google(self) -> None:
        try:
            self._controller.disconnect_google()
        except Exception as exc:  # surface to the Google tab
            self._google_error.setText(f"Disconnect failed: {exc}")
            self._google_error.setHidden(False)

    # ------------------------------------------------------------------ Data

    def _data_tab(self) -> QWidget:
        card = QGroupBox("Data")
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setSpacing(10)

        self._last_backup = QLabel()
        self._last_backup.setObjectName("Caption")
        grid.addWidget(self._last_backup, 0, 0, 1, 2)
        self.refresh_backups()

        btn_backup = QPushButton("Backup now")
        btn_backup.setAccessibleName("Backup now")
        btn_backup.clicked.connect(self._on_backup_now)
        grid.addWidget(btn_backup, 1, 0)

        btn_restore = QPushButton("Restore from backup…")
        btn_restore.setAccessibleName("Restore from backup")
        btn_restore.clicked.connect(self._on_restore_backup)
        grid.addWidget(btn_restore, 1, 1)

        btn_delete = QPushButton("Delete all data")
        btn_delete.setAccessibleName("Delete all data")
        btn_delete.setObjectName("Danger")
        btn_delete.clicked.connect(self._on_delete_all_data)
        grid.addWidget(btn_delete, 2, 0)

        btn_export_json = QPushButton("Export JSON")
        btn_export_json.setAccessibleName("Export JSON")
        btn_export_json.clicked.connect(lambda: self._on_export("json"))
        grid.addWidget(btn_export_json, 2, 1)

        btn_export_md = QPushButton("Export Markdown")
        btn_export_md.setAccessibleName("Export Markdown")
        btn_export_md.clicked.connect(lambda: self._on_export("markdown"))
        grid.addWidget(btn_export_md, 3, 0)

        return card

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
                    f"Backed up: {result['name']}"
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

    # ------------------------------------------------------------------ shared

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
        apply_theme(QApplication.instance(), resolve_theme(theme))

    def _on_autostart_toggled(self, checked: bool) -> None:
        try:
            self._controller.set_autostart(checked)
        except Exception:
            # Revert the checkbox if the Run key cannot be written.
            self._autostart.blockSignals(True)
            self._autostart.setChecked(not checked)
            self._autostart.blockSignals(False)

    def refresh_autostart(self) -> None:
        """Re-read the Run key so the checkbox shows the true state."""
        with contextlib.suppress(Exception):
            self._autostart.setChecked(self._controller.get_autostart())

    @Slot(str, str)
    def _on_controller_error(self, action: str, message: str) -> None:
        if action == "google_connect":
            self._google_error.setText(f"Connect failed: {message}")
            self._google_error.setHidden(False)
        else:
            QMessageBox.warning(self, "Error", message)

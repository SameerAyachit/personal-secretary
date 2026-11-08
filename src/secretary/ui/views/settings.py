"""Settings view placeholder."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class SettingsView(QWidget):
    """Placeholder Settings view (fully wired in Phase 2)."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("Settings"))
        layout.addWidget(QLabel("General, LLM, Google, Data and Privacy settings (wired in Phase 2)."))
        layout.addStretch()

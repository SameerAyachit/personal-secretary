"""Research brief view: run a research brief on a topic and show the sourced
result with citations (plan §14, §12).

The brief and its sources come from the controller's ``research_brief_finished``
signal; the actual research runs on the worker loop, never on the GUI thread.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from secretary.controller import Controller


class ResearchView(QWidget):
    """Research a topic and show the sourced brief with citations."""

    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Research brief")
        title.setObjectName("Section")
        layout.addWidget(title)

        self._topic = QLineEdit()
        self._topic.setPlaceholderText("Research a topic (for example, 'space solar power')")
        self._topic.returnPressed.connect(self._start)
        layout.addWidget(self._topic)

        self._run_btn = QPushButton("Research")
        self._run_btn.setObjectName("Primary")
        self._run_btn.clicked.connect(self._start)
        layout.addWidget(self._run_btn)

        self._status = QLabel("")
        self._status.setObjectName("Caption")
        layout.addWidget(self._status)

        self._error = QLabel("")
        self._error.setObjectName("Caption")
        layout.addWidget(self._error)

        recent_label = QLabel("Recent briefs")
        recent_label.setObjectName("Caption")
        layout.addWidget(recent_label)
        self._recent = QListWidget()
        self._recent.setMaximumHeight(120)
        self._recent.currentRowChanged.connect(self._on_recent_selected)
        layout.addWidget(self._recent)
        self._rows: list[dict] = []
        # Chat-started briefs finish in the background: poll while this tab is visible.
        self._poll = QTimer(self)
        self._poll.setInterval(4000)
        self._poll.timeout.connect(self.refresh)

        self._brief = QTextEdit()
        self._brief.setReadOnly(True)
        self._brief.setPlaceholderText("The brief will appear here with inline source links.")
        layout.addWidget(self._brief)

        self._sources_label = QLabel("Sources")
        self._sources_label.setObjectName("Caption")
        layout.addWidget(self._sources_label)
        self._sources = QListWidget()
        self._sources.setFrameStyle(0)
        layout.addWidget(self._sources)

        controller.research_status.connect(self._status.setText)
        controller.research_brief_finished.connect(self._on_finished)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        self._poll.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._poll.stop()

    def refresh(self) -> None:
        """Reload the recent-briefs list, keeping the selected brief selected."""
        selected = self._recent.currentRow()
        selected_id = self._rows[selected]["id"] if 0 <= selected < len(self._rows) else None
        self._rows = self._controller.list_research_briefs()
        self._recent.blockSignals(True)
        self._recent.clear()
        for row in self._rows:
            self._recent.addItem(QListWidgetItem(f"[{row['status']}] {row['topic']}  ({row['created_at'][:16].replace('T', ' ')})"))
            if row["id"] == selected_id:
                self._recent.setCurrentRow(self._recent.count() - 1)
        self._recent.blockSignals(False)

    def _on_recent_selected(self, index: int) -> None:
        if not 0 <= index < len(self._rows):
            return
        row = self._rows[index]
        self._sources.clear()
        self._error.setText("")
        self._status.setText("")
        if row["status"] == "running":
            self._brief.setPlainText("")
            self._status.setText(f"Still researching '{row['topic']}'... this tab updates by itself.")
        elif row["status"] == "failed":
            self._brief.setPlainText("")
            self._error.setText(row.get("error") or "Research failed.")
        else:
            self._brief.setPlainText(row.get("brief") or "No brief could be written.")
            for i, source in enumerate(json.loads(row.get("sources_json") or "[]"), 1):
                self._sources.addItem(QListWidgetItem(f"[{i}] {source.get('title') or source.get('url', '')}  {source.get('url', '')}"))

    def _start(self) -> None:
        self._run_btn.setEnabled(False)
        self._brief.clear()
        self._sources.clear()
        self._error.setText("")
        self._controller.run_research_brief(self._topic.text())

    @Slot(object)
    def _on_finished(self, result: dict) -> None:
        self._run_btn.setEnabled(True)
        self.refresh()
        self._status.setText("")
        error = result.get("error") if isinstance(result, dict) else None
        if error:
            self._error.setText(error)
            self._brief.setPlainText("")
            return
        self._error.setText("")
        brief = result.get("brief", "") if isinstance(result, dict) else ""
        self._brief.setPlainText(brief or "No brief could be written.")
        sources = result.get("sources", []) if isinstance(result, dict) else []
        self._sources.clear()
        for i, source in enumerate(sources, 1):
            url = source.get("url", "")
            title = source.get("title") or url
            self._sources.addItem(QListWidgetItem(f"[{i}] {title}  {url}"))

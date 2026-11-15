"""Mail view: Gmail triage results (plan §13.4).

The triage job classifies recent unread Gmail messages into a category, an
urgency and a suggested action (fixed enums, produced by a tool-less LLM call).
This view lists them so the work is visible. It is read-only: nothing here can
send or change mail.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from secretary.ui.views.inbox import format_local_time
from secretary.ui.widgets.empty_state import EmptyState

_SUBTITLE = (
    "Recent Gmail messages the assistant has classified: what kind of mail it is, how "
    "urgent it looks and what you might do with it. Read-only; nothing is sent or changed."
)
_EMPTY = (
    "No classified mail yet. Connect Google in Settings; new unread messages are "
    "classified in the background."
)


def _pretty(value: str | None) -> str:
    return (value or "").replace("_", " ").capitalize()


class MailView(QWidget):
    """Lists triaged Gmail messages, newest first."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Mail")
        title.setObjectName("Section")
        layout.addWidget(title)

        subtitle = QLabel(_SUBTITLE)
        subtitle.setObjectName("Caption")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self._list = QListWidget()
        self._list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        layout.addWidget(self._list)

        self._empty = EmptyState(_EMPTY)
        self._empty.hide()
        layout.addWidget(self._empty)

        self.refresh()

    def _timezone(self) -> str:
        try:
            return self._controller.get_config().get("timezone") or "UTC"
        except Exception:
            return "UTC"

    def refresh(self) -> None:
        try:
            rows = self._controller.list_triage()
        except Exception:
            rows = []
        self._list.clear()
        self._list.setVisible(bool(rows))
        self._empty.setVisible(not rows)
        tz_name = self._timezone()
        for row in rows:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, row["id"])
            self._list.addItem(item)
            self._list.setItemWidget(item, self._row_widget(row, tz_name))
        self._fit_rows()

    def _row_widget(self, row: dict, tz_name: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        meta = QLabel(
            f"{_pretty(row.get('category'))}  ·  {_pretty(row.get('urgency'))} urgency  ·  "
            f"Suggested: {_pretty(row.get('suggested_action'))}"
        )
        meta.setObjectName("Caption")
        layout.addWidget(meta)

        subject = QLabel(row.get("subject") or "(no subject)")
        subject.setObjectName("Body")
        subject.setWordWrap(True)
        layout.addWidget(subject)

        sender = QLabel(
            f"{row.get('from_addr', '')}  ·  {format_local_time(row.get('received_at') or '', tz_name)}"
        )
        sender.setObjectName("Caption")
        layout.addWidget(sender)
        return widget

    def _fit_rows(self) -> None:
        width = max(self._list.viewport().width() - 32, 300)
        for index in range(self._list.count()):
            item = self._list.item(index)
            widget = self._list.itemWidget(item)
            if widget is None:
                continue
            layout = widget.layout()
            height = layout.minimumSize().height()
            if layout.hasHeightForWidth():
                height = max(height, layout.heightForWidth(width))
            item.setSizeHint(QSize(width, height + 8))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_rows()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

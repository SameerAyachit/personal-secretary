"""Inbox view: the app's notification log (plan §10.3).

Everything the assistant wants your attention for is written here first:
reminders that fired, research briefs that finished, email send results and
what happened while the app was closed. A filter bar (New / Snoozed /
Acknowledged / Done / All) chooses what is listed. Each row shows what kind of
item it is and when it arrived, and offers every action except the one
matching its current status, plus Reopen once it has left New, so a choice can
always be changed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from secretary.ui.widgets.empty_state import EmptyState

_FILTERS: tuple[tuple[str, str | None, str], ...] = (
    ("unacknowledged", "unacknowledged", "New"),
    ("snoozed", "snoozed", "Snoozed"),
    ("acknowledged", "acknowledged", "Acknowledged"),
    ("done", "done", "Done"),
    ("all", None, "All"),
)
_EMPTY_TEXT = {
    "unacknowledged": (
        "Nothing needs your attention. Reminders, finished research and email "
        "results show up here."
    ),
    "snoozed": "No snoozed items. Snoozed items come back here when their time is up.",
    "acknowledged": "No acknowledged items yet.",
    "done": "No items marked done yet.",
    "all": "The inbox is empty. Reminders, finished research and email results show up here.",
}
_SNOOZE_CHOICES = ("10 minutes", "1 hour", "Tomorrow 9am")
_SUBTITLE = (
    "Your notification log: reminders that fired, research briefs that finished, email "
    "send results, and things that happened while the app was closed. Acknowledge, "
    "snooze or mark items done."
)
_KIND_LABELS = {
    "reminder": "Reminder",
    "briefing": "Briefing",
    "while_away": "While you were away",
    "approval": "Approval",
    "system": "System",
}


def _payload(row: dict) -> dict:
    try:
        value = json.loads(row.get("payload_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def kind_label(row: dict) -> str:
    """Human label for an inbox row, from its kind and payload."""
    payload = _payload(row)
    if payload.get("research_brief_id") is not None:
        return "Research"
    if payload.get("email"):
        return "Email"
    return _KIND_LABELS.get(row.get("kind") or "", "System")


def research_brief_id(row: dict) -> int | None:
    """The research brief an inbox row points at, if any."""
    value = _payload(row).get("research_brief_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def format_local_time(created_at: str, tz_name: str) -> str:
    """'15 Nov, 09:18' in the given time zone (UTC if the zone is unknown)."""
    try:
        when = datetime.fromisoformat((created_at or "").replace("Z", "+00:00"))
    except ValueError:
        return created_at or ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        zone = UTC
    return when.astimezone(zone).strftime("%d %b, %H:%M")


class InboxView(QWidget):
    """Lists inbox items and lets the user acknowledge, snooze or done them."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._label = QLabel("Inbox")
        self._label.setObjectName("Section")
        layout.addWidget(self._label)

        self._subtitle = QLabel(_SUBTITLE)
        self._subtitle.setObjectName("Caption")
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        self._filter_key = "unacknowledged"
        self._filter_buttons: dict[str, QPushButton] = {}
        filter_bar = QHBoxLayout()
        for key, _status, text in _FILTERS:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setChecked(key == self._filter_key)
            button.setAccessibleName(f"Show {text} inbox items")
            button.clicked.connect(lambda checked=False, k=key: self._set_filter(k))
            self._filter_buttons[key] = button
            filter_bar.addWidget(button)
        filter_bar.addStretch()
        layout.addLayout(filter_bar)

        self._list = QListWidget()
        self._list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        layout.addWidget(self._list)

        self._empty = EmptyState(_EMPTY_TEXT[self._filter_key])
        self._empty.hide()
        layout.addWidget(self._empty)

        self._controller.inbox_changed.connect(self.refresh)
        self.refresh()

    def _set_filter(self, key: str) -> None:
        self._filter_key = key
        for name, button in self._filter_buttons.items():
            button.setChecked(name == key)
        self.refresh()

    def _timezone(self) -> str:
        try:
            return self._controller.get_config().get("timezone") or "UTC"
        except Exception:
            return "UTC"

    def refresh(self) -> None:
        status_filter = next(s for k, s, _t in _FILTERS if k == self._filter_key)
        try:
            rows = self._controller.list_inbox(status_filter)
        except Exception:
            rows = []
        self._empty._title.setText(_EMPTY_TEXT[self._filter_key])
        has_rows = bool(rows)
        self._list.setVisible(has_rows)
        self._empty.setVisible(not has_rows)
        self._list.clear()
        tz_name = self._timezone()
        for row in rows:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, row["id"])
            item.setToolTip(f"Status: {row['status'] or 'unacknowledged'}")
            self._list.addItem(item)
            self._list.setItemWidget(item, self._row_widget(row, tz_name))
        self._fit_rows()

    def _row_widget(self, row: dict, tz_name: str) -> QWidget:
        status = row["status"] or "unacknowledged"
        iid = row["id"]
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        meta = QLabel(
            f"{kind_label(row)}  ·  {format_local_time(row.get('created_at') or '', tz_name)}"
            f"  ·  {status}"
        )
        meta.setObjectName("Caption")
        layout.addWidget(meta)

        title = QLabel(row["title"])
        title.setObjectName("Body")
        title.setWordWrap(True)
        layout.addWidget(title)
        if row.get("body"):
            body = QLabel(row["body"])
            body.setObjectName("Caption")
            body.setWordWrap(True)
            layout.addWidget(body)

        buttons = QHBoxLayout()
        buttons.addStretch()
        brief_id = research_brief_id(row)
        if brief_id is not None:
            open_button = QPushButton("Open")
            open_button.setAccessibleName(f"Open research brief for {row['title']}")
            open_button.clicked.connect(
                lambda checked=False, b=brief_id: self._controller.open_research_brief.emit(b)
            )
            buttons.addWidget(open_button)
        if status != "unacknowledged":
            reopen = QPushButton("Reopen")
            reopen.clicked.connect(lambda checked=False, i=iid: self._controller.reopen_inbox(i))
            buttons.addWidget(reopen)
        if status != "acknowledged":
            ack = QPushButton("Ack")
            ack.clicked.connect(lambda checked=False, i=iid: self._controller.ack_inbox(i))
            buttons.addWidget(ack)
        snooze = QPushButton("Snooze")
        menu = QMenu(snooze)
        for choice in _SNOOZE_CHOICES:
            action = menu.addAction(choice)
            action.triggered.connect(
                lambda checked=False, i=iid, c=choice: self._controller.snooze_inbox(i, c.lower())
            )
        menu.addAction("Custom...").triggered.connect(
            lambda checked=False, i=iid: self._snooze_custom(i)
        )
        snooze.setMenu(menu)
        buttons.addWidget(snooze)
        if status != "done":
            done = QPushButton("Done")
            done.setObjectName("Accent")
            done.clicked.connect(lambda checked=False, i=iid: self._on_done(i))
            buttons.addWidget(done)
        layout.addLayout(buttons)
        return widget

    def _ask_complete_task(self, task_title: str) -> bool | None:
        """Ask whether to also complete the task: True yes, False no, None cancel."""
        answer = QMessageBox.question(
            self, "Done",
            f'This reminder is for the task "{task_title}". Mark the task as done too?',
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes,
        )
        if answer == QMessageBox.Cancel:
            return None
        return answer == QMessageBox.Yes

    def _on_done(self, inbox_id: int) -> None:
        task = self._controller.linked_task_for_inbox(inbox_id)
        if task is None:
            self._controller.done_inbox(inbox_id)
            return
        choice = self._ask_complete_task(task["title"])
        if choice is not None:
            self._controller.done_inbox(inbox_id, complete_task=choice)

    def _snooze_custom(self, inbox_id: int) -> None:
        """Ask for a time in the user's words ('in 3 hours', 'friday 9am'); code resolves it."""
        text, accepted = QInputDialog.getText(
            self, "Snooze", "Snooze until (e.g. 'in 3 hours' or 'tomorrow 8am'):"
        )
        if accepted and text.strip():
            self._controller.snooze_inbox(inbox_id, text.strip())

    def _fit_rows(self) -> None:
        """Give each row the height its wrapped content needs at the current width."""
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
        self._fit_rows()

"""Today view (plan 12.2): unacknowledged reminders with Snooze/Done, approvals waiting,
the "While you were away" card, today's events and due tasks in time order, a quick-add
field and a "Plan my day" button.

Everything is read through the controller; the view never touches the store.
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_SNOOZE_CHOICES = ("10 minutes", "1 hour", "Tomorrow 9am")


def _clear(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Section")
    return label


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Caption")
    label.setWordWrap(True)
    return label


class TodayView(QWidget):
    """The day at a glance."""

    navigate_requested = Signal(str)  # a rail label: "Approvals", "Planner", ...

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Quick-add (works without the LLM) and Plan my day.
        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Quick-add a task or reminder")
        self._input.returnPressed.connect(self._on_add)
        add_btn = QPushButton("Add")
        add_btn.setObjectName("Accent")
        add_btn.clicked.connect(self._on_add)
        plan_btn = QPushButton("Plan my day")
        plan_btn.setAccessibleName("Plan my day")
        plan_btn.clicked.connect(self._on_plan)
        add_row.addWidget(self._input, 1)
        add_row.addWidget(add_btn)
        add_row.addWidget(plan_btn)
        layout.addLayout(add_row)

        self._status = _note("")
        self._status.setHidden(True)
        layout.addWidget(self._status)

        # Approvals waiting.
        self._approvals_card = QFrame()
        self._approvals_card.setObjectName("Card")
        approvals_row = QHBoxLayout(self._approvals_card)
        approvals_row.setContentsMargins(12, 8, 12, 8)
        self._approvals_text = QLabel("No approvals waiting.")
        self._approvals_text.setWordWrap(True)
        self._review_approvals = QPushButton("Review")
        self._review_approvals.setObjectName("Accent")
        self._review_approvals.setAccessibleName("Review approvals")
        self._review_approvals.clicked.connect(lambda: self.navigate_requested.emit("Approvals"))
        approvals_row.addWidget(self._approvals_text, 1)
        approvals_row.addWidget(self._review_approvals)
        self._approvals_card.hide()
        layout.addWidget(self._approvals_card)

        # While you were away.
        self._away_card = QLabel()
        self._away_card.setObjectName("Card")
        self._away_card.setWordWrap(True)
        self._away_card.setVisible(False)
        layout.addWidget(self._away_card)

        # Reminders (unacknowledged).
        layout.addWidget(_heading("Reminders"))
        self._reminders_box = QVBoxLayout()
        self._reminders_box.setSpacing(6)
        layout.addLayout(self._reminders_box)

        # Today's events and due tasks.
        layout.addWidget(_heading("Today"))
        self._agenda_box = QVBoxLayout()
        self._agenda_box.setSpacing(6)
        layout.addLayout(self._agenda_box)
        layout.addStretch(1)

        for signal in (
            self._controller.tasks_changed,
            self._controller.inbox_changed,
            self._controller.events_changed,
            self._controller.approvals_changed,
        ):
            signal.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ data

    @Slot()
    def refresh(self) -> None:
        self._refresh_approvals()
        self._refresh_inbox()
        self._refresh_agenda()

    def _refresh_approvals(self) -> None:
        try:
            waiting = len(self._controller.list_pending_actions())
        except Exception:
            waiting = 0
        if waiting:
            noun = "approval" if waiting == 1 else "approvals"
            self._approvals_text.setText(f"{waiting} {noun} waiting for your OK.")
        self._approvals_card.setVisible(bool(waiting))

    def _refresh_inbox(self) -> None:
        try:
            inbox = self._controller.list_inbox()
        except Exception:
            inbox = []
        aways = [row for row in inbox if row.get("kind") == "while_away"]
        if aways:
            self._away_card.setText(aways[0]["body"])
        self._away_card.setVisible(bool(aways))

        _clear(self._reminders_box)
        reminders = [row for row in inbox if row.get("kind") == "reminder"]
        if not reminders:
            self._reminders_box.addWidget(_note("No unacknowledged reminders."))
        for row in reminders:
            self._reminders_box.addWidget(self._reminder_row(row))

    def _refresh_agenda(self) -> None:
        try:
            agenda = self._controller.today_agenda()
        except Exception:
            agenda = []
        _clear(self._agenda_box)
        if not agenda:
            self._agenda_box.addWidget(_note("Nothing is scheduled for today."))
        for entry in agenda:
            prefix = "Task: " if entry["kind"] == "task" else ""
            label = QLabel(f"{entry['time']}   {prefix}{entry['title']}")
            label.setObjectName("Body")
            label.setWordWrap(True)
            self._agenda_box.addWidget(label)

    # ------------------------------------------------------------------ reminders

    def _reminder_row(self, row: dict) -> QWidget:
        inbox_id = row["id"]
        widget = QWidget()
        line = QHBoxLayout(widget)
        line.setContentsMargins(0, 0, 0, 0)
        text = row["title"] + (f" - {row['body']}" if row.get("body") else "")
        label = QLabel(text)
        label.setObjectName("Body")
        label.setWordWrap(True)
        snooze = QPushButton("Snooze")
        snooze.setAccessibleName(f"Snooze {row['title']}")
        menu = QMenu(snooze)
        for choice in _SNOOZE_CHOICES:
            menu.addAction(choice, lambda c=choice, i=inbox_id: self._controller.snooze_inbox(i, c))
        snooze.setMenu(menu)
        done = QPushButton("Done")
        done.setAccessibleName(f"Mark {row['title']} done")
        done.clicked.connect(lambda checked=False, i=inbox_id: self._on_done(i))
        line.addWidget(label, 1)
        line.addWidget(snooze)
        line.addWidget(done)
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

    # ------------------------------------------------------------------ actions

    @Slot()
    def _on_add(self) -> None:
        title = self._input.text().strip()
        if not title:
            return
        if "remind" in title.lower():
            if not self._controller.quick_add_reminder(title):
                self._status.setText(
                    f"Couldn't parse a time from '{title}'. "
                    "Try 'remind me to X in 1 minute' or 'remind me to X at 5pm'."
                )
                self._status.setHidden(False)
                self._input.clear()
                return
            self._status.setText(f"Reminder created: {title}")
        else:
            self._controller.create_task_manual(title, "")
            self._status.setText(f"Task created: {title}")
        self._status.setHidden(False)
        self._input.clear()
        self.refresh()

    @Slot()
    def _on_plan(self) -> None:
        self.navigate_requested.emit("Planner")

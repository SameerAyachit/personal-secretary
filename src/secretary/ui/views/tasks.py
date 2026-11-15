"""Tasks view (plan 12.2): filter chips, search, tick to complete, inline edit, delete.

Quick-add works without the LLM. Filtering and searching are done by the controller
(the same code the chat's ``task_list`` uses), so the list and the chat always agree.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from secretary.ui.views.inbox import format_local_time
from secretary.ui.widgets.empty_state import EmptyState

_FILTERS = (("open", "Open"), ("today", "Today"), ("overdue", "Overdue"), ("done", "Done"))
_EMPTY = {
    "open": "No tasks yet.",
    "today": "Nothing is due today.",
    "overdue": "Nothing is overdue.",
    "done": "No completed tasks yet.",
}


class TasksView(QWidget):
    """Lists tasks and offers a manual quick-add field."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller
        self._filter = "open"
        self._editing: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        bar = QHBoxLayout()
        self._chips: dict[str, QPushButton] = {}
        for key, text in _FILTERS:
            chip = QPushButton(text)
            chip.setCheckable(True)
            chip.setChecked(key == self._filter)
            chip.setAccessibleName(f"Show {text} tasks")
            chip.clicked.connect(lambda checked=False, k=key: self.set_filter(k))
            self._chips[key] = chip
            bar.addWidget(chip)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search tasks")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _text: self.refresh())
        bar.addWidget(self._search, 1)
        layout.addLayout(bar)

        self._list = QListWidget()
        self._list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        layout.addWidget(self._list)

        self._empty = EmptyState(_EMPTY["open"], "Add a task", self._input_focus)
        self._empty.hide()
        layout.addWidget(self._empty)

        add_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Task or reminder (e.g. \"buy groceries\" / \"remind me to call at 5pm\")"
        )
        self._input.returnPressed.connect(self._on_add)
        self._add_btn = QPushButton("Add")
        self._add_btn.setObjectName("Accent")
        self._add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._input)
        add_row.addWidget(self._add_btn)
        layout.addLayout(add_row)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #5B6573; font-size: 12px;")
        self._status.setHidden(True)
        layout.addWidget(self._status)

        self._controller.tasks_changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ helpers

    def titles(self) -> list[str]:
        """Titles currently listed, in order."""
        return [self._list.item(i).data(Qt.UserRole + 1) for i in range(self._list.count())]

    def set_filter(self, key: str) -> None:
        self._filter = key
        self._editing = None
        for name, chip in self._chips.items():
            chip.setChecked(name == key)
        self.refresh()

    def _input_focus(self) -> None:
        self._input.setFocus()

    def _timezone(self) -> str:
        try:
            return self._controller.get_config().get("timezone") or "UTC"
        except Exception:
            return "UTC"

    # ------------------------------------------------------------------ list

    @Slot()
    def refresh(self) -> None:
        try:
            rows = self._controller.list_tasks(self._filter, self._search.text().strip())
        except Exception:
            rows = []
        has_rows = bool(rows)
        self._list.setVisible(has_rows)
        self._empty.setVisible(not has_rows)
        searching = bool(self._search.text().strip())
        self._empty._title.setText("No tasks match your search." if searching else _EMPTY[self._filter])
        self._list.clear()
        tz_name = self._timezone()
        for row in rows:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, row["id"])
            item.setData(Qt.UserRole + 1, row["title"])
            self._list.addItem(item)
            self._list.setItemWidget(item, self._row_widget(row, tz_name))
        self._fit_rows()

    def _row_widget(self, row: dict, tz_name: str) -> QWidget:
        tid = row["id"]
        done = row["status"] == "done"
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        top = QHBoxLayout()
        box = QCheckBox()
        box.setChecked(done)
        box.setAccessibleName(f"Mark {row['title']} {'open' if done else 'done'}")
        box.clicked.connect(lambda checked=False, t=tid, d=done: self._controller.complete_task(t, not d))
        top.addWidget(box)
        if self._editing == tid:
            edit = QLineEdit(row["title"])
            edit.returnPressed.connect(lambda t=tid, e=edit: self._save(t, e.text()))
            top.addWidget(edit, 1)
        else:
            title = QLabel(row["title"])
            title.setObjectName("Body")
            title.setWordWrap(True)
            top.addWidget(title, 1)
        layout.addLayout(top)

        if row.get("due_at"):
            due = QLabel("Due " + format_local_time(row["due_at"], tz_name))
            due.setObjectName("Caption")
            layout.addWidget(due)

        buttons = QHBoxLayout()
        buttons.addStretch()
        if self._editing == tid:
            save = QPushButton("Save")
            save.setObjectName("Accent")
            save.clicked.connect(lambda checked=False, t=tid, w=widget: self._save(t, w.findChild(QLineEdit).text()))
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(lambda checked=False: self._stop_editing())
            buttons.addWidget(save)
            buttons.addWidget(cancel)
        else:
            edit_btn = QPushButton("Edit")
            edit_btn.setAccessibleName(f"Edit {row['title']}")
            edit_btn.clicked.connect(lambda checked=False, t=tid: self._start_editing(t))
            delete = QPushButton("Delete")
            delete.setAccessibleName(f"Delete {row['title']}")
            delete.clicked.connect(lambda checked=False, t=tid: self._controller.delete_task(t))
            buttons.addWidget(edit_btn)
            buttons.addWidget(delete)
        layout.addLayout(buttons)
        return widget

    def _start_editing(self, task_id: int) -> None:
        self._editing = task_id
        self.refresh()

    def _stop_editing(self) -> None:
        self._editing = None
        self.refresh()

    def _save(self, task_id: int, text: str) -> None:
        if self._controller.rename_task(task_id, text):
            self._editing = None
        else:
            self._status.setText("A task needs a title.")
            self._status.setHidden(False)
        self.refresh()

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
        self._fit_rows()

    # ------------------------------------------------------------------ add

    @Slot()
    def _on_add(self) -> None:
        title = self._input.text().strip()
        if not title:
            return
        if "remind" in title.lower():
            if not self._controller.quick_add_reminder(title):
                # No parseable time: say so instead of saving a reminder that
                # can never fire.
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

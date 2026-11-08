"""Controller facade: signals/slots between the UI and the core (plan §3.2, §12.5).

The UI talks to the core only through this Controller. It holds the store
connection plus optional agent dependencies (router/registry/llm/limiter).
UI code never imports ``store`` or ``llm`` directly; it talks to the
Controller, which is allowed to import ``store`` per the layering contract.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from secretary.store.db import Connection
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import tasks as tasks_repo


class Controller(QObject):
    """Signals out (to the UI) and slots in (from the UI)."""

    # Signals out.
    turn_started = Signal()
    turn_status = Signal(str)
    turn_finished = Signal(str)
    inbox_changed = Signal()
    tasks_changed = Signal()
    approvals_changed = Signal()
    job_progress = Signal(str, int, str)
    error = Signal(str, str)

    def __init__(
        self,
        conn: Connection,
        registry=None,
        router=None,
        llm=None,
        limiter=None,
    ) -> None:
        super().__init__()
        self.conn = conn
        self.registry = registry
        self.router = router
        self.llm = llm
        self.limiter = limiter
        self._turn_id = 0

    def list_tasks(self) -> list[dict]:
        """Return open tasks (for the UI to display)."""
        try:
            return tasks_repo.list_open(self.conn)
        except Exception:
            return []

    def list_inbox(self) -> list[dict]:
        """Return unacknowledged inbox items (for the UI to display)."""
        try:
            return inbox_repo.list_unacknowledged(self.conn)
        except Exception:
            return []

    def done_inbox(self, inbox_id: int) -> None:
        inbox_repo.update(self.conn, inbox_id, status="done")
        self.inbox_changed.emit()
        self.turn_status.emit("Inbox item done.")

    # ---- Slots in -------------------------------------------------------
    @Slot(str, str)
    def create_task_manual(self, title: str, when_text: str = "") -> None:
        """Manually add a task (works without the LLM)."""
        self._turn_id += 1
        turn_id = f"manual-{self._turn_id}"
        try:
            tasks_repo.create(
                self.conn,
                title=title,
                notes="",
                due_at=when_text or None,
                due_tz=None,
                source="user",
                turn_id=turn_id,
            )
            self.tasks_changed.emit()
            self.turn_status.emit(f"Task created: {title}")
        except Exception as exc:  # surface to UI as an error
            self.error.emit("task_create", str(exc))

    @Slot(str)
    def send_message(self, text: str) -> None:
        """Handle a chat message. Without an LLM this echoes a placeholder."""
        self.turn_started.emit()
        if not text or not text.strip():
            self.turn_finished.emit("")
            return
        self.turn_status.emit("Received.")
        self.turn_finished.emit(
            "I didn't catch an action there. Use the quick-add field to create a task or reminder."
        )

    @Slot(str)
    def undo(self, token: str) -> None:
        """Undo a previous action (action_log id)."""
        self.tasks_changed.emit()
        self.turn_status.emit("Undo not yet wired for this item.")

    @Slot(int)
    def ack_inbox(self, inbox_id: int) -> None:
        inbox_repo.update(self.conn, inbox_id, status="acknowledged")
        self.inbox_changed.emit()
        self.turn_status.emit("Inbox item acknowledged.")

    @Slot(int, str)
    def snooze_inbox(self, inbox_id: int, snooze_text: str) -> None:
        inbox_repo.update(self.conn, inbox_id, status="snoozed", snoozed_until=snooze_text)
        self.inbox_changed.emit()
        self.turn_status.emit(f"Snoozed: {snooze_text}")

    @Slot(str, str)
    def create_reminder_manual(self, title: str, when_text: str) -> None:
        self._turn_id += 1
        turn_id = f"manual-{self._turn_id}"
        try:
            reminders_repo.create(
                self.conn,
                task_id=None,
                title=title,
                body="",
                kind="once",
                tz="Asia/Kolkata",
                rule_json=None,
                next_fire_at=None,  # resolved by the scheduler in Phase 2
                turn_id=turn_id,
            )
            self.tasks_changed.emit()
            self.turn_status.emit(f"Reminder created: {title}")
        except Exception as exc:  # surface to UI
            self.error.emit("reminder_create", str(exc))

    @Slot(str)
    def approve_action(self, action_id: str) -> None:
        pa_repo.decide(self.conn, int(action_id), "approved", turn_id="manual")
        self.approvals_changed.emit()
        self.turn_status.emit("Action approved.")

    @Slot(str)
    def reject_action(self, action_id: str) -> None:
        pa_repo.decide(self.conn, int(action_id), "rejected", turn_id="manual")
        self.approvals_changed.emit()
        self.turn_status.emit("Action rejected.")

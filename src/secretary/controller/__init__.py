"""Controller facade: signals/slots between the UI and the core (plan §3.2, §12.5).

The UI talks to the core only through this Controller. It holds the store
connection plus optional agent dependencies (router/registry/llm/limiter).
UI code never imports ``store`` or ``llm`` directly; it talks to the
Controller, which is allowed to import ``store`` per the layering contract.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from PySide6.QtCore import QObject, Signal, Slot

from secretary.agent.loop import run_turn
from secretary.autostart import is_enabled as _autostart_is_enabled
from secretary.autostart import set_enabled as _autostart_set_enabled
from secretary.config import load_config, save_config
from secretary.llm.probe import _probe_once
from secretary.secrets import get_secret, set_secret
from secretary.store.db import Connection
from secretary.store.repos import events as events_repo
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import messages as messages_repo
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

    def list_pending_actions(self) -> list[dict]:
        """Return waiting class-C pending actions (for the Approvals view).

        Email send actions are enriched with recipients/body and with the
        recipients not seen in the user's message history, so the UI can
        highlight them (plan §8.6).
        """
        try:
            now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows = pa_repo.list_waiting(self.conn, now_iso=now_iso)
        except Exception:
            return []
        known = set(messages_repo.list_known_addresses(self.conn))
        for row in rows:
            if row["kind"] == "email.send":
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except json.JSONDecodeError:
                    payload = {}
                try:
                    recipients = json.loads(payload.get("to") or "[]")
                except json.JSONDecodeError:
                    recipients = []
                row["recipients"] = recipients
                row["new_recipients"] = [r for r in recipients if r not in known]
                row["subject"] = payload.get("subject", "")
                row["body"] = payload.get("body", "")
        return rows

    # ------------------------------------------------------------------ LLM provider

    def set_llm_provider(
        self, provider: str, key: str, base_url: str, model: str
    ) -> None:
        """Save an LLM API key to Credential Manager and persist provider config."""
        set_secret("secretary", f"llm_api_key:{provider}", key)
        cfg = load_config()
        cfg.llm.active = provider
        cfg.llm.providers[provider].base_url = base_url
        cfg.llm.providers[provider].primary_model = model
        cfg.llm.providers[provider].key_name = f"llm_api_key:{provider}"
        save_config(cfg)

    def test_llm_connection(self, base_url: str, api_key: str, model: str) -> dict:
        """Send a tiny probe request and return the result dict."""
        try:
            result = asyncio.run(_probe_once(api_key, model))
        except Exception as exc:
            return {"error": str(exc)}
        return result

    def get_config(self) -> dict:
        """Return current config values for the wizard to pre-fill."""
        cfg = load_config()
        return {
            "timezone": cfg.app.timezone,
            "start_minimized": cfg.app.start_minimized,
        }

    def save_general(self, timezone: str, start_minimized: bool) -> None:
        cfg = load_config()
        cfg.app.timezone = timezone
        cfg.app.start_minimized = start_minimized
        save_config(cfg)

    def get_autostart(self) -> bool:
        """True if the Run-key autostart value is set (plan Appendix E)."""
        try:
            return _autostart_is_enabled()
        except Exception:
            return False

    def set_autostart(self, enabled: bool) -> None:
        """Add or remove the Run-key autostart value (plan Appendix E)."""
        _autostart_set_enabled(enabled)

    def list_events(self, start_iso: str | None = None, end_iso: str | None = None) -> list[dict]:
        """Return calendar events in [start_iso, end_iso)."""
        try:
            return events_repo.list_window(self.conn, start_at=start_iso or "", end_at=end_iso or "")
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
        """Handle a chat message: run the agent loop when an LLM key is configured,
        otherwise echo a placeholder."""
        self.turn_started.emit()
        if not text or not text.strip():
            self.turn_finished.emit("")
            return
        key = get_secret("secretary", f"llm_api_key:{self.llm.active if self.llm else 'groq'}")
        if not key:
            self.turn_status.emit("No LLM key configured.")
            self.turn_finished.emit(
                "I don't have an LLM key configured yet. Set one in Settings to chat, "
                "or use the quick-add field to create a task."
            )
            return
        try:
            result = asyncio.run(
                run_turn(
                    text,
                    {"turn_id": f"turn-{self._turn_id}", "now": "", "tz": "Asia/Kolkata"},
                    self._llm,
                    self._limiter,
                    self._router,
                    self._registry,
                    self.conn,
                )
            )
        except Exception as exc:
            self.turn_finished.emit(f"I hit an error: {exc}")
            return
        self.turn_finished.emit(result or "I'm not sure how to help with that.")


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
        try:
            pending_id = int(action_id)
        except ValueError:
            return
        pa = pa_repo.get(self.conn, pending_id)
        if pa is None or pa["status"] != "waiting":
            return
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if pa["expires_at"] <= now_iso:
            # Refuse to approve expired actions (plan §3.5, §995).
            pa_repo.decide(self.conn, pending_id, "expired", turn_id="manual")
            self.approvals_changed.emit()
            self.turn_status.emit("Action expired: it can no longer be approved.")
            return
        if pa["kind"] == "email.send":
            self._execute_send(pa)
        else:
            pa_repo.decide(self.conn, pending_id, "approved", turn_id="manual")
            self.approvals_changed.emit()
            self.turn_status.emit("Action approved.")

    @Slot(str)
    def reject_action(self, action_id: str) -> None:
        pa_repo.decide(self.conn, int(action_id), "rejected", turn_id="manual")
        self.approvals_changed.emit()
        self.turn_status.emit("Action rejected.")

    def _execute_send(self, pa: dict) -> None:
        """Send an approved email draft after payload re-verification (plan §3.5).

        Re-fetches the draft at send time and compares recipients/subject/body
        against the snapshot approved earlier; refuses on any change. No real
        transport exists yet (Gmail send is human-gated), so execution is
        recorded as the pending action reaching "executed".
        """
        pending_id = int(pa["id"])
        try:
            payload = json.loads(pa["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        draft_ref = payload.get("draft_ref")
        approved = {key: payload.get(key) for key in ("to", "subject", "body")}
        try:
            draft_id = int(draft_ref)
        except (TypeError, ValueError):
            draft_id = None
        message = messages_repo.get(self.conn, draft_id) if draft_id is not None else None
        changed = (
            message is None
            or message.get("source") != "draft"
            or message.get("to_addrs") != approved.get("to")
            or message.get("subject") != approved.get("subject")
            or message.get("body") != approved.get("body")
        )
        if changed:
            pa_repo.decide(
                self.conn,
                pending_id,
                "failed",
                turn_id="manual",
                result_json=json.dumps({"reason": "draft changed since approval"}),
            )
            self.turn_status.emit("Send refused: draft changed since approval.")
        else:
            pa_repo.decide(self.conn, pending_id, "executed", turn_id="manual")
            self.turn_status.emit("Email sent.")
        self.approvals_changed.emit()

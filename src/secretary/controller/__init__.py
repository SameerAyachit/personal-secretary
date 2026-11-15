"""Controller facade: signals/slots between the UI and the core (plan §3.2, §12.5).

The UI talks to the core only through this Controller. It holds the store
connection plus optional agent dependencies (router/registry/llm/limiter).
UI code never imports ``store`` or ``llm`` directly; it talks to the
Controller, which is allowed to import ``store`` per the layering contract.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from functools import partial
from zoneinfo import ZoneInfo

from PySide6.QtCore import QObject, Signal, Slot

from secretary.agent.loop import run_turn
from secretary.autostart import is_enabled as _autostart_is_enabled
from secretary.autostart import set_enabled as _autostart_set_enabled
from secretary.config import default_timezone, load_config, save_config
from secretary.controller.data import DataMixin
from secretary.controller.google import GoogleMixin
from secretary.controller.llm_settings import LLMSettingsMixin, get_active_llm_key
from secretary.integrations.google.gmail import GmailError, GmailPermissionError
from secretary.store.db import Connection
from secretary.store.repos import chat as chat_repo
from secretary.store.repos import events as events_repo
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import messages as messages_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import research_briefs as briefs_repo
from secretary.store.repos import tasks as tasks_repo
from secretary.timeparse.when import extract_when_phrase, resolve_when
from secretary.tools.email import email_send_prepare
from secretary.tools.planning import plan_day
from secretary.tools.research import run_research_job

logger = logging.getLogger(__name__)


def _run_in_thread(fn) -> None:
    """Run ``fn`` on a daemon thread so network I/O never blocks the GUI thread."""
    threading.Thread(target=fn, daemon=True).start()


class Controller(DataMixin, GoogleMixin, LLMSettingsMixin, QObject):
    """Signals out (to the UI) and slots in (from the UI)."""

    # Signals out.
    turn_started = Signal()
    turn_status = Signal(str)
    turn_finished = Signal(str)
    inbox_changed = Signal()
    tasks_changed = Signal()
    events_changed = Signal()
    approvals_changed = Signal()
    google_connected = Signal()
    job_progress = Signal(str, int, str)
    research_status = Signal(str)  # research brief progress
    research_brief_finished = Signal(object)  # dict: {brief, sources, ...}
    models_loaded = Signal(str, list)  # provider, models (for AI dropdown)
    connection_tested = Signal(str, dict)  # provider, result dict (for Test connection)
    error = Signal(str, str)

    def __init__(
        self,
        conn: Connection,
        registry=None,
        router=None,
        llm=None,
        limiter=None,
        submit_coro=None,
    ) -> None:
        super().__init__()
        self.conn = conn
        self.registry = registry
        self.router = router
        self.llm = llm
        self.limiter = limiter
        self._turn_id = 0
        # Coroutine submit callable (worker thread loop). Agent turns run on the
        # persistent worker loop (plan §3.1), never on the Qt main thread, so the
        # UI stays responsive and the shared httpx client keeps one event loop.
        self._submit_coro = submit_coro
        # Background references (set by __main__ after creation) so data-safety
        # operations can stop them before wiping the DB (plan E18).
        self._scheduler = None
        self._worker = None
        self._gmail = None
        self._run_background = _run_in_thread

    def _new_turn_id(self, prefix: str = "turn") -> str:
        """Globally unique turn id (never repeats across launches).

        Idempotency keys hash the turn id, so a per-launch counter would make
        the same request in a new session collide with an old reminder.
        """
        self._turn_id += 1
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    def set_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    def set_gmail_client(self, gmail) -> None:
        """Gmail client used to send approved emails (None until Google connects)."""
        self._gmail = gmail

    def set_worker(self, worker) -> None:
        self._worker = worker
    def list_tasks(self) -> list[dict]:
        """Return open tasks (for the UI to display)."""
        try:
            return tasks_repo.list_open(self.conn)
        except Exception:
            return []

    def list_research_briefs(self, limit: int = 20) -> list[dict]:
        """Recent research briefs (running, done, failed), newest first, for the Research tab."""
        try:
            return self.conn.read(lambda c: briefs_repo.list_recent(c, limit))
        except Exception:
            return []

    def list_inbox(self, status: str | None = "unacknowledged") -> list[dict]:
        """Inbox items with the given status (default: new ones); ``None`` returns all."""
        try:
            return inbox_repo.list_by_status(self.conn, status)
        except Exception:
            return []

    def list_inbox_preview(self, limit: int | None = None) -> list[dict]:
        """Return unacknowledged inbox items, newest first (for the tray
        overflow hint). When ``limit`` is None all items are returned so the
        caller can compute the overflow hint accurately."""
        try:
            rows = inbox_repo.list_unacknowledged(self.conn)
            return rows if limit is None else rows[:limit]
        except Exception:
            return []

    # ------------------------------------------------------------------ Chat history

    def get_recent_chat_messages(self, limit: int = 8) -> list[dict]:
        """Return recent user/assistant chat messages for turn context history,
        oldest first, so the model can follow up on previous exchanges."""
        try:
            return chat_repo.recent_messages(self.conn, limit)
        except Exception:
            return []

    def _store_chat_message(self, role: str, content: str, turn_id: str | None = None) -> None:
        """Persist one chat message (best-effort: history must never block a turn)."""
        try:
            chat_repo.add_message(self.conn, role, content, turn_id)
        except Exception:
            logger.exception("could not store chat message")

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

    def list_drafts(self) -> list[dict]:
        """Unsent email drafts for Approvals > Drafts."""
        try:
            drafts = messages_repo.list_drafts(self.conn)
            now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            waiting = pa_repo.list_waiting(self.conn, now_iso=now_iso)
        except Exception:
            return []
        requested: set[str] = set()
        for action in waiting:
            if action["kind"] == "email.send":
                with contextlib.suppress(json.JSONDecodeError, AttributeError):
                    requested.add(str(json.loads(action["payload_json"] or "{}").get("draft_ref")))
        rows = []
        for draft in drafts:
            try:
                recipients = json.loads(draft.get("to_addrs") or "[]")
            except json.JSONDecodeError:
                recipients = []
            rows.append({
                "id": draft["id"],
                "recipients": recipients,
                "subject": draft.get("subject") or "",
                "body": draft.get("body") or "",
                "send_requested": str(draft["id"]) in requested,
            })
        return rows

    @Slot(int)
    def queue_draft_send(self, draft_id: int) -> None:
        """Ask for approval to send a draft (class C: nothing is sent yet)."""
        if any(d["id"] == draft_id and d["send_requested"] for d in self.list_drafts()):
            return
        result = email_send_prepare(self.conn, "manual", {"draft_ref": str(draft_id)})
        if "error" in result:
            self.turn_status.emit(f"Could not request send: {result['error']}")
            return
        self.approvals_changed.emit()
        self.turn_status.emit("Send requested. Approve it below to send the email.")

    @Slot(int)
    def discard_draft(self, draft_id: int) -> None:
        self.conn.write(lambda c: messages_repo.discard_draft(c, int(draft_id), turn_id="manual"))
        # A waiting send request for this draft must not outlive it.
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for action in pa_repo.list_waiting(self.conn, now_iso=now_iso):
            if action["kind"] != "email.send":
                continue
            with contextlib.suppress(json.JSONDecodeError, AttributeError):
                if str(json.loads(action["payload_json"] or "{}").get("draft_ref")) == str(draft_id):
                    pa_repo.decide(self.conn, int(action["id"]), "rejected", turn_id="manual")
        self.approvals_changed.emit()

    # ------------------------------------------------------------------ LLM provider



    def get_config(self) -> dict:
        """Return current config values for the wizard to pre-fill."""
        cfg = load_config()
        return {
            "timezone": cfg.app.timezone,
            "start_minimized": cfg.app.start_minimized,
            "theme": cfg.app.theme,
        }





    def set_theme(self, theme: str) -> None:
        """Persist the UI theme (system|light|dark)."""
        cfg = load_config()
        cfg.app.theme = theme
        save_config(cfg)

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
    def send_message(self, text: str, priority: str = "interactive") -> None:
        """Handle a chat message: run the agent loop when an LLM key is configured,
        otherwise echo a placeholder."""
        self.turn_started.emit()
        if not text or not text.strip():
            self.turn_finished.emit("")
            return
        key = get_active_llm_key()
        if not key:
            self.turn_status.emit("No LLM key configured.")
            self.turn_finished.emit(
                "I don't have an LLM key configured yet. Set one in Settings to chat, "
                "or use the quick-add field to create a task."
            )
            return
        if self.llm is None:
            # Key present but model missing/placeholder: do not call the provider.
            self.turn_status.emit("No model selected.")
            self.turn_finished.emit(
                "No model selected. Open Settings > AI and pick one."
            )
            return
        turn_id = self._new_turn_id()
        self.turn_status.emit("Thinking...")
        logger.info("chat turn %s: send_message user_text=%r", turn_id, text)
        if self._submit_coro is None:
            self.turn_finished.emit(
                "I hit an error: LLM worker loop is not available."
            )
            return
        cfg = load_config()
        tz_name = cfg.app.timezone or "UTC"
        zone = ZoneInfo(tz_name)
        now_local = datetime.now(UTC).astimezone(zone)
        history = self.get_recent_chat_messages(limit=cfg.llm.history_messages)
        self._store_chat_message("user", text, turn_id)
        coro = run_turn(
            text,
            {
                "turn_id": turn_id,
                "now": now_local.isoformat(),
                "tz": tz_name,
                "today_iso": now_local.date().isoformat(),
                "priority": priority,
                "history": history,
            },
            self.llm,
            self.limiter,
            self.router,
            self.registry,
            self.conn,
        )
        future = self._submit_coro(coro)
        future.add_done_callback(partial(self._on_turn_done, turn_id))

    def _on_turn_done(self, turn_id: str, future: asyncio.Future) -> None:
        """Deliver a completed turn result back to the UI via a Qt signal.

        Runs on the worker thread; turn_finished is delivered to GUI receivers
        (main thread) queued by Qt, so the UI never blocks while a turn runs.
        """
        try:
            result = future.result()
        except Exception as exc:
            logger.exception("chat turn %s: run_turn raised", turn_id)
            self.turn_finished.emit(f"I hit an error: {exc}")
            return
        self._store_chat_message("assistant", result or "", turn_id)
        self.events_changed.emit()  # the turn may have created calendar events
        # A turn can also queue approvals, drafts, inbox items and tasks.
        self.approvals_changed.emit()
        self.inbox_changed.emit()
        self.tasks_changed.emit()
        self.turn_finished.emit(result or "I'm not sure how to help with that.")

    @Slot(str)
    def run_research_brief(self, topic: str) -> None:
        """Research a topic on the worker loop; the result comes back through
        ``research_brief_finished`` as a dict {brief, sources, ...}."""
        topic = (topic or "").strip()
        if not topic:
            self.research_brief_finished.emit({"brief": "", "sources": [], "error": "Enter a topic to research."})
            return
        if self._submit_coro is None:
            self.research_brief_finished.emit(
                {"brief": "", "sources": [], "error": "Research worker is not available."}
            )
            return
        self.turn_status.emit("Researching...")
        self.research_status.emit("Researching...")
        future = self._submit_coro(run_research_job(self.conn, topic))
        future.add_done_callback(self._on_research_done)

    def _on_research_done(self, future: asyncio.Future) -> None:
        """Deliver a completed research brief back to the UI."""
        self.research_status.emit("")
        try:
            result = future.result()
        except Exception as exc:  # surface exact error, never secrets
            logger.exception("research brief failed")
            self.research_brief_finished.emit({"brief": "", "sources": [], "error": f"Research failed: {exc}"})
            return
        self.research_brief_finished.emit(result or {"brief": "", "sources": []})

    def create_task_at(self, title: str, start_at_iso: str, tz: str | None = None) -> None:
        """Create a task scheduled at a given local time (planner slot)."""
        self._turn_id += 1
        turn_id = f"manual-{self._turn_id}"
        try:
            tasks_repo.create(
                self.conn,
                title=title,
                notes="",
                due_at=start_at_iso,
                due_tz=tz or default_timezone(),
                source="user",
                turn_id=turn_id,
            )
            self.tasks_changed.emit()
            self.turn_status.emit(f"Task created: {title}")
        except Exception as exc:
            self.error.emit("task_create", str(exc))

    def get_free_slots(self, date_iso: str, tz: str | None = None, min_duration_minutes: int = 30) -> dict:
        """Code-assisted planner: compute free slots in a day (9:00-17:00 local)
        around existing calendar events. Returns {date, tz, free_slots}."""
        return plan_day(
            self.conn,
            "planner",
            {"date_text": date_iso, "tz": tz or default_timezone(), "min_duration_minutes": min_duration_minutes},
        )

    @Slot(int)
    def ack_inbox(self, inbox_id: int) -> None:
        inbox_repo.update(self.conn, inbox_id, status="acknowledged")
        self.inbox_changed.emit()
        self.turn_status.emit("Inbox item acknowledged.")

    @Slot(int)
    def reopen_inbox(self, inbox_id: int) -> None:
        """Put an acknowledged, snoozed or done item back to New."""
        inbox_repo.update(
            self.conn, inbox_id, status="unacknowledged",
            snoozed_until=None, acknowledged_at=None,
        )
        self.inbox_changed.emit()
        self.turn_status.emit("Inbox item reopened.")

    @Slot(int, str)
    def snooze_inbox(self, inbox_id: int, snooze_text: str) -> None:
        cfg = load_config()
        tz_name = cfg.app.timezone or "UTC"
        zone = ZoneInfo(tz_name)
        now_local = datetime.now(UTC).astimezone(zone)
        try:
            fire_local = resolve_when(snooze_text, now_local, tz_name)
        except Exception:
            # Can't parse the snooze text: store it verbatim so the UI shows
            # what really happened instead of silently succeeding.
            inbox_repo.update(self.conn, inbox_id, status="snoozed", snoozed_until=snooze_text)
            self.inbox_changed.emit()
            self.turn_status.emit(f"Snooze not understood: '{snooze_text}'")
            return
        snoozed_until = fire_local.astimezone(UTC).isoformat()
        inbox_repo.update(self.conn, inbox_id, status="snoozed", snoozed_until=snoozed_until)
        self.inbox_changed.emit()
        self.turn_status.emit(
            f"Snoozed until {fire_local.strftime('%a %d %b, %I:%M %p %Z')}"
        )

    @Slot(str, str)
    def create_reminder_manual(self, title: str, when_text: str) -> bool:
        """Create a once-reminder from ``when_text`` (resolved in code).

        Returns False (after telling the UI why) when no time can be resolved,
        so a reminder that could never fire is never created.
        """
        cfg = load_config()
        tz_name = cfg.app.timezone or "UTC"
        now_local = datetime.now(UTC).astimezone(ZoneInfo(tz_name))
        try:
            fire_local = resolve_when(when_text, now_local, tz_name)
        except Exception:
            self.turn_status.emit(
                f"Couldn't parse '{when_text}' — please include a time "
                "(e.g. 'in 1 minute', 'tomorrow at 9am')."
            )
            return False
        try:
            reminders_repo.create(
                self.conn,
                task_id=None,
                title=title,
                body="",
                kind="once",
                tz=tz_name,
                rule_json=None,
                next_fire_at=fire_local.astimezone(UTC).isoformat(),
                turn_id=self._new_turn_id("manual"),
            )
        except Exception as exc:  # surface to UI
            self.error.emit("reminder_create", str(exc))
            return False
        self.tasks_changed.emit()
        self.turn_status.emit(f"Reminder created: {title}")
        return True

    def quick_add_reminder(self, text: str) -> bool:
        """Quick-add "remind me to X in 10 minutes": the time phrase is
        extracted and resolved here (timeparse), never in the UI."""
        return self.create_reminder_manual(text, extract_when_phrase(text))

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
        """Send an approved email draft through Gmail (plan §3.5, ADR-005).

        Re-fetches the draft at send time and compares recipients/subject/body
        against the snapshot approved earlier; refuses on any change. Only the
        first waiting -> approved transition proceeds, so a double click cannot
        send twice. The network call runs off the GUI thread.
        """
        pending_id = int(pa["id"])
        try:
            payload = json.loads(pa["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        approved = {key: payload.get(key) for key in ("to", "subject", "body")}
        try:
            draft_id = int(payload.get("draft_ref"))
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
            self._fail_send(pending_id, "draft changed since approval", from_waiting=True)
            self.turn_status.emit("Send refused: draft changed since approval.")
            return
        gmail = self._gmail
        if gmail is None:
            self._fail_send(
                pending_id, "Google is not connected: connect Google in Settings, then approve again",
                from_waiting=True,
            )
            self.turn_status.emit("Connect Google in Settings to send email.")
            return
        try:
            to_addrs = [str(a) for a in json.loads(approved["to"] or "[]")]
        except (TypeError, json.JSONDecodeError):
            to_addrs = []
        if not to_addrs:
            self._fail_send(pending_id, "draft has no recipient", from_waiting=True)
            self.turn_status.emit("Send refused: draft has no recipient.")
            return
        # Atomic claim: only one caller can move waiting -> approved.
        if not pa_repo.decide(self.conn, pending_id, "approved", turn_id="manual"):
            return
        self.approvals_changed.emit()
        self.turn_status.emit("Sending email...")
        subject, body = approved["subject"] or "", approved["body"] or ""
        self._run_background(
            partial(self._send_worker, gmail, pending_id, draft_id, to_addrs, subject, body)
        )

    def _send_worker(
        self, gmail, pending_id: int, draft_id: int | None, to_addrs, subject: str, body: str
    ) -> None:
        try:
            result = gmail.send_message(to_addrs, subject, body)
        except GmailPermissionError:
            self._fail_send(
                pending_id, "Reconnect Google in Settings (needs permission to send email)"
            )
            self.turn_status.emit("Could not send: reconnect Google in Settings.")
            return
        except GmailError as exc:
            logger.warning("email send failed: %s", exc)
            self._fail_send(pending_id, f"Gmail send failed: {exc}")
            self.turn_status.emit("Sending failed. See Approvals for details.")
            return
        except Exception as exc:
            logger.exception("email send crashed")
            self._fail_send(pending_id, f"Unexpected error while sending: {exc}")
            self.turn_status.emit("Sending failed. See Approvals for details.")
            return
        self.conn.write(
            lambda c: pa_repo.finish(
                c, pending_id, "executed", turn_id="manual",
                result_json=json.dumps({"gmail_id": str((result or {}).get("id", ""))}),
            )
        )
        if draft_id is not None:
            self.conn.write(lambda c: messages_repo.mark_sent(c, draft_id, turn_id="manual"))
        self._send_note(f"Email sent to {', '.join(to_addrs)}", f"Subject: {subject}")
        self.approvals_changed.emit()
        self.turn_status.emit(f"Email sent to {', '.join(to_addrs)}.")

    def _fail_send(self, pending_id: int, reason: str, *, from_waiting: bool = False) -> None:
        result = json.dumps({"reason": reason})
        if from_waiting:
            pa_repo.decide(self.conn, pending_id, "failed", turn_id="manual", result_json=result)
        else:
            self.conn.write(
                lambda c: pa_repo.finish(
                    c, pending_id, "failed", turn_id="manual", result_json=result
                )
            )
        self._send_note("Email was not sent", reason)
        self.approvals_changed.emit()

    def _send_note(self, title: str, body: str) -> None:
        self.conn.write(
            lambda c: inbox_repo.create(
                c, kind="system", title=title, body=body, payload_json="{}", turn_id="manual"
            )
        )
        self.inbox_changed.emit()

    # ---- Data: backups, restore, delete-all, export (plan §5.5, §941-942) ----







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
import shutil
import threading
import time
import uuid
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication

from secretary.agent.loop import run_turn
from secretary.autostart import is_enabled as _autostart_is_enabled
from secretary.autostart import set_enabled as _autostart_set_enabled
from secretary.config import load_config, save_config
from secretary.integrations.google.clients import build_clients
from secretary.integrations.google.oauth import (
    GoogleOAuthError,
    GoogleOAuthFlow,
    connected,
    disconnect,
    is_invalid_grant,
)
from secretary.llm.factory import build_llm
from secretary.llm.openai_compat import OpenAICompatClient
from secretary.llm.probe import _probe_once
from secretary.paths import backups_dir, credentials_path, db_path, logs_dir
from secretary.secrets import delete_secret, get_secret, set_secret
from secretary.store.backup import backup, list_backups, prune_backups, restore
from secretary.store.db import Connection
from secretary.store.repos import events as events_repo
from secretary.store.repos import facts as facts_repo
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import messages as messages_repo
from secretary.store.repos import pending_actions as pa_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.store.repos import settings as settings_repo
from secretary.store.repos import tasks as tasks_repo
from secretary.timeparse.when import resolve_when
from secretary.tools.planning import plan_day
from secretary.tools.research import research_brief_tool

logger = logging.getLogger(__name__)

def get_active_llm_key() -> str | None:
    """Return the API key for the configured LLM provider from Credential Manager.

    Uses the same service and key name that ``diagnose`` checks: service
    ``Secretary``, key ``llm_api_key:{provider}`` where ``provider`` is the
    active provider from config.
    """
    cfg = load_config()
    provider = cfg.llm.active
    return get_secret(_llm_key_name(provider))


def _llm_key_name(provider: str) -> str:
    """Credential key name for a provider: ``llm_api_key:{provider}``."""
    return f"llm_api_key:{provider}"


class Controller(QObject):
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

    def _new_turn_id(self, prefix: str = "turn") -> str:
        """Globally unique turn id (never repeats across launches).

        Idempotency keys hash the turn id, so a per-launch counter would make
        the same request in a new session collide with an old reminder.
        """
        self._turn_id += 1
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    def set_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    def set_worker(self, worker) -> None:
        self._worker = worker
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

    def resolve_when_text(self, text: str, tz_name: str | None = None) -> str | None:
        """Resolve a user time expression to a UTC ISO string, or None if unparseable.

        Runs in code (never by the LLM). Used by the UI quick-add path.
        """
        cfg = load_config()
        tz_name = tz_name or cfg.app.timezone or "UTC"
        zone = ZoneInfo(tz_name)
        now_local = datetime.now(UTC).astimezone(zone)
        try:
            fire_local = resolve_when(text, now_local, tz_name)
            return fire_local.astimezone(UTC).isoformat()
        except Exception:
            return None

    def get_recent_chat_messages(self, limit: int = 8) -> list[dict]:
        """Return recent user/assistant chat messages for turn context history.

        Ordered oldest-first, suitable for passing as ``ctx["history"]`` to the
        agent loop so the model can follow up on previous exchanges.
        """
        try:
            rows = self.conn.execute(
                "SELECT role, content FROM messages WHERE role IN ('user','assistant') "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
        except Exception:
            return []

    def _store_chat_message(self, role: str, content: str, turn_id: str | None = None) -> None:
        """Persist one chat message to the conversations/messages table."""
        try:
            conv = self.conn.execute(
                "SELECT id FROM conversations ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if conv is None:
                self.conn.execute(
                    "INSERT INTO conversations(title, created_at) VALUES(?,?)",
                    ("Chat", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
                )
                conv_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                conv_id = conv[0]
            self.conn.execute(
                "INSERT INTO messages(conversation_id, role, content, turn_id, created_at) "
                "VALUES(?,?,?,?,?)",
                (conv_id, role, content, turn_id, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
        except Exception:
            # History is best-effort; a failure must never block a chat turn.
            pass

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
        """Save an LLM API key to Credential Manager and persist provider config.

        Never overwrites a stored key with a blank field: if ``key`` is empty,
        the previously saved key is left in place so the user can't accidentally
        erase it by leaving the field blank.
        """
        cfg = load_config()
        cfg.llm.active = provider
        cfg.llm.providers[provider].base_url = base_url
        cfg.llm.providers[provider].primary_model = model
        cfg.llm.providers[provider].key_name = _llm_key_name(provider)
        save_config(cfg)
        if key and key.strip():
            set_secret(_llm_key_name(provider), key.strip())
        self.rebuild_llm()

    def rebuild_llm(self) -> None:
        """Rebuild the LLM client and limiter from the current config.

        Called when the provider, key, or model changes so the active turn
        loop uses the new settings without a restart (plan A5). Limiter values
        come from config, not code constants.
        """
        self.llm, self.limiter = build_llm(load_config(), get_active_llm_key())

    def get_config(self) -> dict:
        """Return current config values for the wizard to pre-fill."""
        cfg = load_config()
        return {
            "timezone": cfg.app.timezone,
            "start_minimized": cfg.app.start_minimized,
            "theme": cfg.app.theme,
        }

    def get_llm_config(self) -> dict:
        """Return LLM provider config for the AI settings tab (no secrets)."""
        cfg = load_config()
        providers: dict[str, dict] = {}
        for name, prov in cfg.llm.providers.items():
            providers[name] = {
                "base_url": prov.base_url,
                "model": prov.primary_model,
                "key_name": prov.key_name,
            }
        return {"active": cfg.llm.active, "providers": providers}

    def get_llm_key_status(self, provider: str | None = None) -> dict:
        """Return LLM key status for the AI settings tab (never the value).

        Status: "missing" (no key in Credential Manager), "placeholder"
        (key shorter than 20 chars or starts with fake/test), or "saved".
        """
        cfg = load_config()
        provider = provider or cfg.llm.active
        key_name = f"llm_api_key:{provider}"
        key = get_secret(key_name)
        if not key:
            return {"status": "missing", "provider": provider, "key_name": key_name}
        if len(key) < 20 or key.lower().startswith(("fake", "test")):
            return {"status": "placeholder", "provider": provider, "key_name": key_name}
        return {"status": "saved", "provider": provider, "key_name": key_name}

    @Slot(str)
    def get_available_models(self, provider: str | None = None) -> None:
        """List the provider's models on the worker loop; emit models_loaded.

        Never blocks the Qt thread. Returns immediately; results arrive via
        the models_loaded signal (provider, list[str]). Falls back to the
        configured primary_model on failure.
        """
        cfg = load_config()
        provider = provider or cfg.llm.active
        prov = cfg.llm.providers.get(provider)
        if prov is None:
            self.models_loaded.emit(provider, [])
            return
        key = get_secret(_llm_key_name(provider))
        if not key:
            self.models_loaded.emit(provider, [])
            return
        client = OpenAICompatClient(base_url=prov.base_url, api_key=key, model=prov.primary_model or "x")

        async def _list_and_close() -> list[str]:
            try:
                return await client.list_models()
            finally:
                await client.aclose()

        if self._submit_coro is None:
            self.models_loaded.emit(provider, [])
            return
        future = self._submit_coro(_list_and_close())
        future.add_done_callback(
            lambda f: self.models_loaded.emit(
                provider,
                f.result() if not f.exception() else [],
            )
        )

    @Slot(str, str, str)
    def test_llm_connection(self, base_url: str, api_key: str, model: str) -> None:
        """Send a tiny probe request on the worker loop; emit connection_tested.

        Uses the stored key when the field is blank, and the provider's
        base_url (not a hardcoded Groq URL) so it works for Gemini too.
        """
        cfg = load_config()
        provider = cfg.llm.active
        key = api_key.strip() if api_key and api_key.strip() else get_active_llm_key()
        if not key:
            self.connection_tested.emit(
                provider,
                {"error": "No LLM key configured. Save one in Settings > AI first."},
            )
            return

        async def _probe() -> dict:
            try:
                return await _probe_once(key, model, base_url=base_url)
            except Exception as exc:  # surface exact error, never secrets
                return {"error": str(exc)}

        if self._submit_coro is None:
            self.connection_tested.emit(
                provider, {"error": "Worker loop not available"}
            )
            return
        future = self._submit_coro(_probe())
        future.add_done_callback(
            lambda f: self.connection_tested.emit(
                provider, f.result() if not f.exception() else {"error": str(f.exception())}
            )
        )

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

    def get_google_connected(self) -> bool:
        """True if a Google refresh token is stored in Credential Manager."""
        try:
            return connected()
        except Exception:
            return False

    def get_google_sync_status(self) -> dict:
        """Return the last Google Calendar sync status for the UI chip."""
        try:
            failed = settings_repo.get(self.conn, "google_sync_failed") == "1"
            error = settings_repo.get(self.conn, "google_sync_error") or ""
            return {"failed": bool(failed), "error": str(error)}
        except Exception:
            return {"failed": False, "error": ""}

    @Slot()
    def connect_google(self) -> None:
        """Run the OAuth consent flow (credentials.json) on a background thread
        so the UI is not blocked while the user authenticates in the browser.
        """
        threading.Thread(target=self._connect_google_background, daemon=True).start()

    def _connect_google_background(self) -> None:
        """Run the OAuth consent flow on a background thread.

        Every step is logged (without secrets) and any failure is surfaced
        through the ``error`` signal so the Settings view can show a clear
        message instead of silently leaving Google "not connected".
        """
        logger.info("google connect flow started")
        try:
            creds_path = credentials_path()
            logger.info("google credentials file: %s", creds_path)
            flow = GoogleOAuthFlow.from_credentials_file(creds_path)
            logger.info("google consent flow starting (browser + loopback)")
            flow.run()
            self.rebuild_google_client()
            logger.info("google refresh token stored in Credential Manager")
        except FileNotFoundError:
            msg = (
                "credentials.json not found in the data root. "
                "Download it from the Google Cloud console and place it next to config.toml."
            )
            logger.warning("google connect: %s", msg)
            self.error.emit("google_connect", msg)
            return
        except GoogleOAuthError as exc:
            if is_invalid_grant(exc):
                disconnect()
            msg = str(exc)
            logger.warning("google connect failed: %s", msg)
            self.error.emit("google_connect", msg)
            return
        except Exception as exc:  # unexpected failure: never swallow in the daemon thread
            msg = f"google connect failed: {exc}"
            logger.exception("google connect failed unexpectedly")
            self.error.emit("google_connect", msg)
            return
        self.google_connected.emit()
        logger.info("google connect flow completed")

    @Slot()
    def disconnect_google(self) -> None:
        """Remove the Google refresh token (Reconnect Google path)."""
        with contextlib.suppress(Exception):
            disconnect()
        self.google_connected.emit()

    def rebuild_google_client(self) -> None:
        """Rebuild Gmail + Calendar clients when Google connects (no restart).

        Hands the new clients to the running scheduler so sync and event
        write-back start immediately (plan D16).
        """
        gmail, calendar = build_clients(credentials_path())
        if self._scheduler is not None:
            self._scheduler.set_google_clients(gmail, calendar)

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
        turn_id = f"research-{self._turn_id}"
        self._turn_id += 1
        coro = research_brief_tool(self.conn, turn_id, {"topic": topic, "depth": "standard"})
        future = self._submit_coro(coro)
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

    def create_task_at(self, title: str, start_at_iso: str, tz: str = "Asia/Kolkata") -> None:
        """Create a task scheduled at a given local time (planner slot)."""
        self._turn_id += 1
        turn_id = f"manual-{self._turn_id}"
        try:
            tasks_repo.create(
                self.conn,
                title=title,
                notes="",
                due_at=start_at_iso,
                due_tz=tz,
                source="user",
                turn_id=turn_id,
            )
            self.tasks_changed.emit()
            self.turn_status.emit(f"Task created: {title}")
        except Exception as exc:
            self.error.emit("task_create", str(exc))

    def get_free_slots(self, date_iso: str, tz: str = "Asia/Kolkata", min_duration_minutes: int = 30) -> dict:
        """Code-assisted planner: compute free slots in a day (9:00-17:00 local)
        around existing calendar events. Returns {date, tz, free_slots}."""
        return plan_day(
            self.conn,
            "planner",
            {"date_text": date_iso, "tz": tz, "min_duration_minutes": min_duration_minutes},
        )

    @Slot(int)
    def ack_inbox(self, inbox_id: int) -> None:
        inbox_repo.update(self.conn, inbox_id, status="acknowledged")
        self.inbox_changed.emit()
        self.turn_status.emit("Inbox item acknowledged.")

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
    def create_reminder_manual(self, title: str, when_text: str) -> None:
        cfg = load_config()
        tz_name = cfg.app.timezone or "UTC"
        zone = ZoneInfo(tz_name)
        now_local = datetime.now(UTC).astimezone(zone)
        self._turn_id += 1
        turn_id = f"manual-{self._turn_id}"
        try:
            fire_utc = None
            if when_text and when_text.strip():
                fire_local = resolve_when(when_text, now_local, tz_name)
                fire_utc = fire_local.astimezone(UTC).isoformat()
            else:
                # No time could be resolved: don't create a reminder that can
                # never fire. Tell the UI what really happened.
                self.turn_status.emit(
                    f"Couldn't parse '{when_text}' — please include a time "
                    "(e.g. 'in 1 minute', 'tomorrow at 9am')."
                )
                return
            reminders_repo.create(
                self.conn,
                task_id=None,
                title=title,
                body="",
                kind="once",
                tz=tz_name,
                rule_json=None,
                next_fire_at=fire_utc,
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
            self.turn_status.emit("Approved, sending is not enabled yet.")

    # ---- Data: backups, restore, delete-all, export (plan §5.5, §941-942) ----

    def list_backups(self) -> list[dict]:
        """Return available backups, newest first (Settings Data page)."""
        out: list[dict] = []
        for p in list_backups(backups_dir()):
            st = p.stat()
            out.append({"name": p.name, "path": str(p), "size": st.st_size, "mtime": st.st_mtime})
        return out

    def backup_now(self) -> dict | None:
        """Force a backup now (Settings Data 'Backup now')."""
        backups_dir().mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        dst = backups_dir() / f"secretary-{stamp}.db"
        backup(self.conn, dst)
        prune_backups(backups_dir(), 7)
        return {"name": dst.name, "path": str(dst)}

    def restore_backup(self, backup_name: str) -> dict:
        """Restore a backup: stop background threads, safety-copy the current DB,
        replace it, then quit so the app restarts into the restored data
        (Settings Data 'Restore')."""
        self._stop_background()
        src = backups_dir() / backup_name
        if not src.exists():
            return {"error": "backup not found"}
        # Do not replace a database that is open.
        if self.conn is not None and self.conn._con is not None:
            with contextlib.suppress(Exception):
                self.conn.close()
        safety = restore(src, db_path())
        app = QApplication.instance()
        if app is not None:
            app.quit()
        return {"safety": str(safety), "restored": backup_name}

    def delete_all_data(self) -> dict:
        """Wipe the DB, backups, logs and Credential Manager entries, then quit
        (Settings Data 'Delete all data', plan §941)."""
        self._stop_background()
        self.conn.close()
        db = db_path()
        with contextlib.suppress(FileNotFoundError):
            db.unlink()
        for suffix in ("-wal", "-shm"):
            with contextlib.suppress(FileNotFoundError):
                Path(str(db) + suffix).unlink()
        bd = backups_dir()
        if bd.exists():
            shutil.rmtree(bd)
        ld = logs_dir()
        if ld.exists():
            # Close logging handlers before deleting the logs folder.
            for handler in logging.root.handlers[:]:
                handler.close()
                logging.root.removeHandler(handler)
            for name in logging.Logger.manager.loggerDict:
                logger_obj = logging.Logger.manager.loggerDict[name]
                if isinstance(logger_obj, logging.Logger):
                    for handler in logger_obj.handlers[:]:
                        handler.close()
                        logger_obj.removeHandler(handler)
            shutil.rmtree(ld)
        # Remove LLM keys as well as Google ones.
        delete_secret("google_token")
        delete_secret("google_client_id")
        cfg = load_config()
        for provider in list(cfg.llm.providers.keys()):
            delete_secret(_llm_key_name(provider))
        app = QApplication.instance()
        if app is not None:
            app.quit()
        return {"deleted": True}

    def _stop_background(self) -> None:
        """Stop scheduler and worker before destructive data operations."""
        if self._scheduler is not None:
            with contextlib.suppress(Exception):
                self._scheduler.stop()
        if self._worker is not None:
            with contextlib.suppress(Exception):
                self._worker.stop()

    def export_data(self, fmt: str = "json") -> dict:
        """Export tasks, reminders, events and facts as JSON or Markdown
        (Settings Data 'Export', plan §942)."""
        payload = {
            "tasks": tasks_repo.list_open(self.conn),
            "reminders": reminders_repo.list_all(self.conn),
            "events": events_repo.list_window(self.conn, start_at="", end_at=""),
            "facts": facts_repo.list_all(self.conn),
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        backups_dir().mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        if fmt == "markdown":
            lines = ["# Secretary export", f"Generated: {payload['exported_at']}", ""]
            for section in ("tasks", "reminders", "events", "facts"):
                lines.append(f"## {section.title()}")
                for row in payload[section]:
                    lines.append("- " + " | ".join(f"{k}={v}" for k, v in row.items() if v is not None))
                lines.append("")
            text = "\n".join(lines)
            dst = backups_dir() / f"secretary-export-{stamp}.md"
            dst.write_text(text, encoding="utf-8")
        else:
            dst = backups_dir() / f"secretary-export-{stamp}.json"
            dst.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"name": dst.name, "path": str(dst), "format": fmt}

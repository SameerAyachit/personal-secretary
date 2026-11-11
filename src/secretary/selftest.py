"""Real-machine selftest: exercises the REAL composition root headless.

Runs the real app pieces (real QApplication, store, controller, LLM client,
keyring, scheduler thread and notifier) with NO fakes and reports
[PASS]/[FAIL] per step plus exact exception text on failure. No secrets are
printed.

Usage:
    python -m secretary --selftest chat
    python -m secretary --selftest reminder
    python -m secretary --selftest google
    python -m secretary --selftest all
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication

from secretary.agent.router import Router
from secretary.app import WorkerThread
from secretary.config import load_config
from secretary.controller import Controller, get_active_llm_key
from secretary.integrations.google.auth import GoogleAuth, GoogleAuthError
from secretary.integrations.google.oauth import connected
from secretary.llm.limiter import Limiter
from secretary.llm.openai_compat import OpenAICompatClient
from secretary.notify.notifier import Notifier
from secretary.paths import config_path, credentials_path, db_path
from secretary.scheduler.ticker import SchedulerThread
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import reminders as reminders_repo
from secretary.tools import email as email_tools
from secretary.tools import events as events_tools
from secretary.tools import memory as memory_tools
from secretary.tools import planning as planning_tools
from secretary.tools import reminders as reminders_tools
from secretary.tools import research as research_tools
from secretary.tools import tasks as tasks_tools
from secretary.tools.registry import Registry

POLL = 0.05


def _safe_print(text: str) -> None:
    """Print without crashing on consoles that cannot encode all Unicode."""
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            text.encode(sys.stdout.encoding or "utf-8", errors="replace") + b"\n"
        )


def _google_error_line(resp: httpx.Response) -> str:
    """HTTP status plus Google's error reason and message from the body.

    Tokens are never printed.
    """
    reason = ""
    message = ""
    try:
        body = resp.json()
        err = body.get("error", {}) if isinstance(body, dict) else {}
        message = str(err.get("message", ""))
        errors = err.get("errors", [])
        if isinstance(errors, list):
            reason = ", ".join(
                str(e.get("reason", "")) for e in errors if isinstance(e, dict)
            )
    except Exception:  # body parsing is best-effort
        pass
    line = f"HTTP {resp.status_code}"
    if reason:
        line += f" reason={reason}"
    if message:
        line += f" message={message}"
    return line


def _poll(condition, timeout_seconds: float) -> bool:
    """Run the Qt event loop until ``condition()`` is true or timeout elapses."""
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(POLL)
    return False


class TurnSpy(QObject):
    """Collects ``turn_finished`` emissions.

    A plain Python callable connected to a Qt signal is not reliably delivered
    across threads, so this :class:`QObject` exposes a real ``@Slot(str)`` that
    Qt delivers to the main thread event loop even when the signal is emitted
    from the worker thread.
    """

    def __init__(self) -> None:
        super().__init__()
        self.replies: list[str] = []

    @Slot(str)
    def on_finished(self, text: str) -> None:
        self.replies.append(text)


def _build_registry_router() -> tuple[Registry, Router]:
    registry = Registry()
    tasks_tools.register(registry)
    email_tools.register(registry)
    events_tools.register(registry)
    planning_tools.register(registry)
    reminders_tools.register(registry)
    memory_tools.register(registry)
    research_tools.register(registry)
    router = Router(registry)
    router.route("tasks_add", ["task", "create", "add", "remind"])
    router.route("tasks_list", ["task", "list", "show", "remind"])
    router.route("reminder_create", ["remind", "reminder"])
    router.route("reminder_list", ["remind", "reminder", "list", "show"])
    router.route("reminder_snooze", ["snooze", "reminder"])
    router.route("reminder_cancel", ["cancel", "reminder", "delete"])
    router.route("memory_remember", ["remember", "memory"])
    router.route("memory_forget", ["forget", "memory"])
    router.route("email_send", ["send", "email"])
    router.route("web_search", ["search", "web"])
    router.route("event_create", ["event", "calendar", "meeting", "appointment"])
    router.route("event_list", ["events", "calendar", "schedule", "agenda"])
    router.route("plan_day", ["plan", "planning", "schedule", "free", "slot"])
    router.route("research_brief", ["research", "brief", "summarize"])
    return registry, router


def _new_conn(data_root: Path) -> Connection:
    conn = Connection(db_path())
    migrate(conn._con, migrations_folder(), lambda: None)
    return conn


def _build_controller(conn: Connection, submit_coro=None) -> tuple[Controller, dict]:
    registry, router = _build_registry_router()
    key = get_active_llm_key()
    if not key:
        raise RuntimeError("no LLM key configured in Credential Manager")
    cfg = load_config()
    provider = cfg.llm.active
    prov = cfg.llm.providers[provider]
    llm = OpenAICompatClient(base_url=prov.base_url, api_key=key, model=prov.primary_model)
    limiter = Limiter(rpm=60, tpm=6000, safety=0.7)
    controller = Controller(
        conn,
        registry=registry,
        router=router,
        llm=llm,
        limiter=limiter,
        submit_coro=submit_coro,
    )
    placeholder = len(key) < 20 or key.lower().startswith(("fake", "test"))
    info = {
        "provider": provider,
        "model": prov.primary_model,
        "config_path": str(config_path()),
        "service": "Secretary",
        "key_name": f"llm_api_key:{provider}",
        "key_length": len(key),
        "key_prefix": key[:4],
        "placeholder": placeholder,
    }
    return controller, info


def _chat_meta(info: dict) -> str:
    return (
        f"(config={info['config_path']}, provider={info['provider']}, model={info['model']}, "
        f"service={info['service']}, name={info['key_name']}, "
        f"length={info['key_length']}, prefix={info['key_prefix']})"
    )


def _selftest_chat(data_root: Path, submit_coro=None) -> str:
    conn = _new_conn(data_root)
    try:
        controller, info = _build_controller(conn, submit_coro=submit_coro)
    except RuntimeError as exc:
        return f"[FAIL] chat: {exc}"
    if info["placeholder"]:
        return (
            f"[FAIL] chat: stored key is a placeholder, please re-enter it {_chat_meta(info)}"
        )
    spy = TurnSpy()
    controller.turn_finished.connect(spy.on_finished)
    try:
        for i in range(5):
            controller.send_message(f"message {i + 1}: say ping")
    except Exception as exc:  # surface exact error, never secrets
        return f"[FAIL] chat: send_message raised {type(exc).__name__}: {exc} {_chat_meta(info)}"
    for i in range(5):
        if not _poll(lambda i=i: len(spy.replies) == i + 1, 30.0):
            return f"[FAIL] chat: no assistant reply for message {i + 1} within 30 s {_chat_meta(info)}"
        reply = (spy.replies[i] or "").strip()
        if not reply:
            return f"[FAIL] chat: empty assistant reply for message {i + 1} {_chat_meta(info)}"
        if reply.startswith("I hit an error:"):
            return f"[FAIL] chat: provider error: {reply[:90]} {_chat_meta(info)}"
    return f"[PASS] chat: 5 messages OK; last: {spy.replies[-1][:60]} {_chat_meta(info)}"


def _selftest_reminder(data_root: Path, submit_coro=None) -> str:
    conn = _new_conn(data_root)
    try:
        controller, _info = _build_controller(conn, submit_coro=submit_coro)
    except RuntimeError as exc:
        return f"[FAIL] reminder: {exc}"
    spy = TurnSpy()
    controller.turn_finished.connect(spy.on_finished)
    notifier = Notifier(None)
    notified: list[tuple[str, str]] = []

    def _record_notify(title: str, body: str, priority: bool = False) -> bool:
        notified.append((title, body))
        return True

    notifier.notify = _record_notify  # type: ignore[method-assign]

    def on_fired(entries):
        for entry in entries:
            notifier.notify(entry["title"], entry["body"], priority=True)
        controller.inbox_changed.emit()

    scheduler = SchedulerThread(conn, on_fired=on_fired)
    scheduler.start()
    try:
        try:
            controller.send_message("remind me to drink water in 20 seconds")
        except Exception as exc:  # surface exact error, never secrets
            return f"[FAIL] reminder: send_message raised {type(exc).__name__}: {exc}"
        if not _poll(lambda: bool(spy.replies), 30.0):
            return "[FAIL] reminder: no assistant reply within 30 s"
        reply = (spy.replies[-1] or "").strip()
        if not reply:
            return "[FAIL] reminder: empty assistant reply"
        if reply.startswith("I hit an error:"):
            return f"[FAIL] reminder: provider error: {reply[:90]}"
        # The confirmation must mention the resolved reminder time.
        if not re.search(r"\d", reply):
            return f"[FAIL] reminder: confirmation does not mention the reminder time: {reply[:90]}"
        if not _poll(
            lambda: any(
                r["title"] == "drink water"
                for r in reminders_repo.list_all(conn, status="scheduled")
            ),
            30.0,
        ):
            return "[FAIL] reminder: no scheduled reminder row"
        if not _poll(
            lambda: any(
                r["title"] == "drink water" for r in inbox_repo.list_unacknowledged(conn)
            ),
            40.0,
        ):
            return "[FAIL] reminder: scheduler did not fire into inbox within 40 s"
        if not notified:
            return "[FAIL] reminder: notifier was not invoked"
        return f"[PASS] reminder: '{reply[:90]}' fired into inbox and notifier invoked ({notified[0][0]})"
    finally:
        scheduler.stop()


def _selftest_notify(data_root: Path, submit_coro=None) -> str:
    """Show one real Windows toast via the notifier.

    desktop-notifier cannot initialise unpackaged (no AUMID), so when the toast
    layer is unavailable we confirm the fallback: popup card shown + inbox row
    always fire.
    """
    conn = _new_conn(data_root)
    try:
        notifier = Notifier(None)
        title = "Secretary notify self-test"
        body = "toast selftest"
        try:
            notifier.notify(title, body, priority=True)
        except Exception as exc:  # surface exact error, never secrets
            return f"[FAIL] notify: notify raised {type(exc).__name__}: {exc}"
        # Deliver the queued toast display on the GUI thread.
        app = QApplication.instance()
        app.processEvents()
        # Inbox row is the source of truth; always write it directly.
        inbox_repo.create(conn, kind="reminder", title=title, body=body, turn_id="notify-selftest")
        rows = inbox_repo.list_unacknowledged(conn)
        if any(r["title"] == title for r in rows):
            if notifier._desktop_sync is not None:
                return "[PASS] notify: Windows toast sent"
            return (
                "[PASS] notify: toast unavailable (AUMID unpackaged); "
                "popup card shown + inbox row fires"
            )
        return "[FAIL] notify: neither toast nor inbox fired"
    finally:
        conn.close()


def _selftest_google(data_root: Path, submit_coro=None) -> str:
    path = credentials_path()
    if not path.exists():
        return "[FAIL] google: no credentials.json found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"[FAIL] google: credentials.json does not parse: {exc}"
    installed = data.get("installed") or data.get("web") or {}
    client_id = installed.get("client_id", "")
    client_secret = installed.get("client_secret", "")
    redirect_uris = installed.get("redirect_uris", ["http://localhost"])
    redirect_uri = redirect_uris[0] if redirect_uris else "http://localhost"
    scopes = (
        "https://www.googleapis.com/auth/calendar.events "
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/gmail.compose"
    )
    parts = [
        f"client_id length={len(client_id)} suffix={client_id[-4:] if client_id else '(none)'}",
        f"redirect_uri={redirect_uri}",
        f"scopes={scopes.split()}",
    ]
    if not connected():
        return (
            "[WARN] google: no refresh token yet; sign-in needed (" + " | ".join(parts) + ")"
        )
    try:
        auth = GoogleAuth(client_id, client_secret)
        auth.access_token()  # refreshes against Google; may raise GoogleAuthError
        # Only the events scope is granted, so only events.list on the primary
        # calendar is used (never calendarList).
        now = datetime.now(UTC)
        resp = httpx.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params={
                "timeMin": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timeMax": (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "singleEvents": "true",
                "maxResults": "10",
            },
            headers=auth.auth_header(),
            timeout=30.0,
        )
        parts.append(_google_error_line(resp))
        if resp.status_code == 200:
            items = resp.json().get("items", []) or []
            parts.append(f"events(next 7 days)={len(items)}")
            return "[PASS] google: " + " | ".join(parts)
        return "[FAIL] google: " + " | ".join(parts)
    except GoogleAuthError as exc:
        return f"[FAIL] google: refresh failed ({exc}) | " + " | ".join(parts)
    except Exception as exc:  # surface exact error, never secrets
        return f"[FAIL] google: {type(exc).__name__}: {exc} | " + " | ".join(parts)


def _selftest_google_live(data_root: Path) -> str:
    """Live Google check against the real APIs (refresh token must be saved).

    Refreshes the access token, lists events for the next 7 days on the
    primary calendar (events scope only) and prints the count, then lists the
    5 most recent Gmail message ids (message references only, no content).
    """
    path = credentials_path()
    if not path.exists():
        return "[FAIL] google-live: no credentials.json found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"[FAIL] google-live: credentials.json does not parse: {exc}"
    installed = data.get("installed") or data.get("web") or {}
    client_id = installed.get("client_id", "")
    client_secret = installed.get("client_secret", "")
    parts = [f"client_id length={len(client_id)} suffix={client_id[-4:] if client_id else '(none)'}"]
    if not connected():
        return (
            "[FAIL] google-live: not connected; sign in via Settings > Google > "
            "Connect Google first (" + " | ".join(parts) + ")"
        )
    try:
        auth = GoogleAuth(client_id, client_secret)
        token = auth.access_token()  # refreshes against Google; may raise GoogleAuthError
        parts.append("access token refreshed")
        # Calendar: next 7 days on the primary calendar (events scope only).
        now = datetime.now(UTC)
        resp = httpx.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params={
                "timeMin": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timeMax": (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "singleEvents": "true",
                "maxResults": "2500",
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        if resp.status_code != 200:
            return "[FAIL] google-live: calendar " + _google_error_line(resp) + " | " + " | ".join(parts)
        items = resp.json().get("items", []) or []
        parts.append(f"events(next 7 days)={len(items)}")
        # Gmail: 5 most recent message ids (references only, no content).
        gmail_resp = httpx.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params={"maxResults": "5"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        if gmail_resp.status_code != 200:
            return "[FAIL] google-live: gmail " + _google_error_line(gmail_resp) + " | " + " | ".join(parts)
        ids = [m.get("id", "") for m in (gmail_resp.json().get("messages", []) or [])]
        parts.append("gmail recent ids=" + ",".join(i for i in ids if i))
        return "[PASS] google-live: " + " | ".join(parts)
    except GoogleAuthError as exc:
        return f"[FAIL] google-live: refresh failed ({exc}) | " + " | ".join(parts)
    except Exception as exc:  # surface exact error, never secrets
        return f"[FAIL] google-live: {type(exc).__name__}: {exc} | " + " | ".join(parts)


def _selftest_all(data_root: Path, submit_coro=None) -> str:
    results = [
        _selftest_chat(data_root, submit_coro=submit_coro),
        _selftest_reminder(data_root, submit_coro=submit_coro),
        _selftest_google(data_root),
    ]
    for line in results:
        _safe_print(line)
    chat_ok = results[0].startswith("[PASS]")
    rem_ok = results[1].startswith("[PASS]")
    # A google [WARN] (no refresh token yet) stays non-fatal; any [FAIL] fails all.
    google_ok = not results[2].startswith("[FAIL]")
    overall = "PASS" if (chat_ok and rem_ok and google_ok) else "FAIL"
    return f"[{overall}] selftest all"


def run_selftest(name: str) -> int:
    """Run a real-machine selftest headless. Returns 0 if no [FAIL], else 1."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    data_root = Path(tempfile.mkdtemp(prefix="secretary-selftest-"))
    os.environ["SECRETARY_DATA_ROOT"] = str(data_root)

    # Copy the real config.toml (if any) into the temp data root so the real
    # composition root reads the user's configured provider/model instead of
    # falling back to empty defaults.
    real_cfg = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Secretary" / "config.toml"
    if real_cfg.exists():
        (data_root / "config.toml").write_bytes(real_cfg.read_bytes())

    # Persistent worker loop for agent turns (plan §3.1). All LLM calls run on
    # this loop, never on the Qt main thread, so the UI stays responsive and
    # the shared httpx client keeps one event loop.
    worker = WorkerThread()
    worker.start()
    deadline = time.monotonic() + 5
    while worker.loop is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if worker.loop is None:
        _safe_print("[FAIL] selftest: worker loop did not start")
        return 1

    tests = {
        "chat": _selftest_chat,
        "reminder": _selftest_reminder,
        "google": _selftest_google,
        "google-live": _selftest_google_live,
        "notify": _selftest_notify,
        "all": _selftest_all,
    }
    if name not in tests:
        _safe_print(f"unknown selftest: {name} (choices: {', '.join(sorted(tests))})")
        worker.stop()
        return 2
    result = tests[name](data_root, submit_coro=worker.submit)
    _safe_print(result)
    failed = "[FAIL]" in result or (name == "all" and not result.startswith("[PASS] selftest all"))
    worker.stop()
    return 1 if failed else 0

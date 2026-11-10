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
import tempfile
import time
from pathlib import Path

import httpx
from PySide6.QtWidgets import QApplication

from secretary.agent.router import Router
from secretary.config import load_config
from secretary.controller import Controller, get_active_llm_key
from secretary.integrations.google.auth import GoogleAuth, GoogleAuthError
from secretary.integrations.google.oauth import connected
from secretary.llm.limiter import Limiter
from secretary.llm.openai_compat import OpenAICompatClient
from secretary.notify.notifier import Notifier
from secretary.paths import credentials_path, db_path
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


def _build_controller(conn: Connection) -> tuple[Controller, dict]:
    registry, router = _build_registry_router()
    key = get_active_llm_key()
    if not key:
        raise RuntimeError("no LLM key configured in Credential Manager")
    cfg = load_config()
    provider = cfg.llm.active
    prov = cfg.llm.providers[provider]
    llm = OpenAICompatClient(base_url=prov.base_url, api_key=key, model=prov.primary_model)
    limiter = Limiter(rpm=60, tpm=6000, safety=0.7)
    controller = Controller(conn, registry=registry, router=router, llm=llm, limiter=limiter)
    placeholder = len(key) < 20 or key.lower().startswith(("fake", "test"))
    info = {
        "provider": provider,
        "model": prov.primary_model,
        "service": "Secretary",
        "key_name": f"llm_api_key:{provider}",
        "key_length": len(key),
        "key_prefix": key[:4],
        "placeholder": placeholder,
    }
    return controller, info


def _chat_meta(info: dict) -> str:
    return (
        f"(provider={info['provider']}, model={info['model']}, "
        f"service={info['service']}, name={info['key_name']}, "
        f"length={info['key_length']}, prefix={info['key_prefix']})"
    )


def _selftest_chat(data_root: Path) -> str:
    conn = _new_conn(data_root)
    try:
        controller, info = _build_controller(conn)
    except RuntimeError as exc:
        return f"[FAIL] chat: {exc}"
    if info["placeholder"]:
        return (
            f"[FAIL] chat: stored key is a placeholder, please re-enter it {_chat_meta(info)}"
        )
    replies = []
    controller.turn_finished.connect(replies.append)
    try:
        controller.send_message("hey")
    except Exception as exc:  # surface exact error, never secrets
        return f"[FAIL] chat: send_message raised {type(exc).__name__}: {exc} {_chat_meta(info)}"
    if not _poll(lambda: bool(replies and replies[-1]), 30.0):
        return f"[FAIL] chat: no assistant reply within 30 s {_chat_meta(info)}"
    reply = (replies[-1] or "").strip()
    if not reply:
        return f"[FAIL] chat: empty assistant reply {_chat_meta(info)}"
    if reply.startswith("I hit an error:"):
        return f"[FAIL] chat: provider error: {reply[:90]} {_chat_meta(info)}"
    return f"[PASS] chat: {reply[:90]} {_chat_meta(info)}"


def _selftest_reminder(data_root: Path) -> str:
    conn = _new_conn(data_root)
    try:
        controller, _info = _build_controller(conn)
    except RuntimeError as exc:
        return f"[FAIL] reminder: {exc}"
    notifier = Notifier(None)
    notified = []
    notifier.notified.connect(notified.append)

    def on_fired(entries):
        for entry in entries:
            notifier.notify(entry["title"], entry["body"], priority=True)
        controller.inbox_changed.emit()

    scheduler = SchedulerThread(conn, on_fired=on_fired)
    scheduler.start()
    try:
        replies = []
        controller.turn_finished.connect(replies.append)
        try:
            controller.send_message("remind me to drink water in 20 seconds")
        except Exception as exc:  # surface exact error, never secrets
            return f"[FAIL] reminder: send_message raised {type(exc).__name__}: {exc}"
        if not _poll(lambda: bool(replies and replies[-1]), 30.0):
            return "[FAIL] reminder: no assistant reply within 30 s"
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
        return f"[PASS] reminder: fired into inbox and notifier invoked ({notified[0][0]})"
    finally:
        scheduler.stop()


def _selftest_google(data_root: Path) -> str:
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
        resp = httpx.get(
            "https://www.googleapis.com/calendar/v3/users/me/calendarList",
            headers=auth.auth_header(),
            timeout=30.0,
        )
        parts.append(f"calendar list HTTP {resp.status_code}")
        if resp.status_code == 200:
            return "[PASS] google: " + " | ".join(parts)
        return "[FAIL] google: " + " | ".join(parts)
    except GoogleAuthError as exc:
        return f"[FAIL] google: refresh failed ({exc}) | " + " | ".join(parts)
    except Exception as exc:  # surface exact error, never secrets
        return f"[FAIL] google: {type(exc).__name__}: {exc} | " + " | ".join(parts)


def _selftest_all(data_root: Path) -> str:
    results = [
        _selftest_chat(data_root),
        _selftest_reminder(data_root),
        _selftest_google(data_root),
    ]
    for line in results:
        print(line)
    chat_ok = results[0].startswith("[PASS]")
    rem_ok = results[1].startswith("[PASS]")
    goo_ok = results[2].startswith("[PASS]") or results[2].startswith("[WARN]")
    overall = "PASS" if (chat_ok and rem_ok and goo_ok) else "FAIL"
    return f"[{overall}] selftest all"


def run_selftest(name: str) -> int:
    """Run a real-machine selftest headless. Returns 0 if no [FAIL], else 1."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    data_root = Path(tempfile.mkdtemp(prefix="secretary-selftest-"))
    os.environ["SECRETARY_DATA_ROOT"] = str(data_root)
    tests = {
        "chat": _selftest_chat,
        "reminder": _selftest_reminder,
        "google": _selftest_google,
        "all": _selftest_all,
    }
    if name not in tests:
        print(f"unknown selftest: {name} (choices: {', '.join(sorted(tests))})")
        return 2
    result = tests[name](data_root)
    print(result)
    failed = "[FAIL]" in result or (name == "all" and not result.startswith("[PASS] selftest all"))
    return 1 if failed else 0

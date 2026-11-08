"""Startup smoke test.

Builds the REAL composition root used by ``python -m secretary`` (plan
§3.1 / ``__main__.main()``): QApplication, single-instance app, store connection
+ migrations, Controller, tool registry + router, search provider + cache, and
the MainWindow. Runs with a temp data root (``SECRETARY_DATA_ROOT``) and
offscreen Qt, lets the event loop start, then closes the window.

This exercises ``SearchCache.__init__``, which previously called bare
``COMMIT`` on a connection running with ``isolation_level=None`` and crashed
with ``sqlite3.OperationalError: cannot commit - no transaction is active``.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from secretary.agent.router import Router
from secretary.app import create_app
from secretary.controller import Controller
from secretary.integrations.search.provider import CircuitBreaker, DDGSSearchProvider, SearchService
from secretary.paths import db_path
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.tools import email as email_tools
from secretary.tools import registry as tools_registry
from secretary.tools import tasks as tasks_tools
from secretary.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def data_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("secretary-data")
    os.environ["SECRETARY_DATA_ROOT"] = str(root)
    yield root


def test_real_composition_root_starts_and_closes(data_root):
    app = create_app([])
    assert app.is_primary()
    app.start_worker()
    try:
        conn = Connection(db_path())
        try:
            migrate(conn._con, migrations_folder(), lambda: None)
            controller = Controller(conn)

            registry = tools_registry.Registry()
            tasks_tools.register(registry)
            email_tools.register(registry)
            router = Router(registry)
            router.route("tasks_add", ["task", "create", "add", "remind"])
            router.route("tasks_list", ["task", "list", "show", "remind"])
            router.route("reminders_add", ["remind", "reminder"])

            # Search provider + cache + breaker: this is what exercised the bug.
            provider = DDGSSearchProvider()
            breaker = CircuitBreaker(failures=3, open_minutes=10)
            search_service = SearchService(conn, provider, breaker)
            conn.search_provider = search_service

            window = MainWindow(controller)
            window.show()
            assert window.isVisible()

            # Let the event loop start, then close the window.
            app.app.processEvents()
            window.close()
            app.app.processEvents()
        finally:
            conn.close()
    finally:
        app.cleanup()

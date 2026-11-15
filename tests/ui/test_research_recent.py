"""Research tab lists recent background briefs (chat-started ones included) and shows them."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import research_briefs as repo
from secretary.ui.views.research import ResearchView


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "r.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    migrate(con, migrations_folder(), lambda: None)
    return Connection(tmp)


def test_recent_briefs_are_listed_newest_first_and_selectable(qapp):
    conn = _conn()
    done = conn.write(lambda c: repo.create(c, "air quality"))
    conn.write(
        lambda c: repo.finish(c, done, "AQI brief [1](https://e.com/a).", [{"url": "https://e.com/a", "title": "Paper"}], partial=False)
    )
    conn.write(lambda c: repo.create(c, "still going"))
    failed = conn.write(lambda c: repo.create(c, "broken"))
    conn.write(lambda c: repo.fail(c, failed, "provider down"))

    view = ResearchView(Controller(conn))
    view.refresh()
    labels = [view._recent.item(i).text() for i in range(view._recent.count())]
    assert [("broken" in t, "still going" in t, "air quality" in t) for t in labels] == [
        (True, False, False), (False, True, False), (False, False, True)
    ]
    assert "failed" in labels[0].lower() and "running" in labels[1].lower()

    view._recent.setCurrentRow(2)  # the finished brief
    assert "AQI brief" in view._brief.toPlainText()
    assert "https://e.com/a" in view._sources.item(0).text()

    view._recent.setCurrentRow(0)  # the failed one explains why
    assert "provider down" in view._error.text()
    view._recent.setCurrentRow(1)  # the running one says so
    assert "still" in view._status.text().lower()


def test_refresh_keeps_the_selected_brief(qapp):
    conn = _conn()
    first = conn.write(lambda c: repo.create(c, "one"))
    conn.write(lambda c: repo.finish(c, first, "Brief one.", [], partial=False))
    view = ResearchView(Controller(conn))
    view.refresh()
    view._recent.setCurrentRow(0)
    conn.write(lambda c: repo.create(c, "two"))
    view.refresh()
    assert "Brief one." in view._brief.toPlainText()
    assert view._recent.count() == 2

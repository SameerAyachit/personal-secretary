"""Text-scaling check (plan section 12): main views stay usable at 125% and 150%.

Windows display scaling mostly shows up in Qt as larger text. Offscreen Qt has no real
DPI, so this test scales the application font by the same factor, grabs each main view
and saves the PNGs under docs/screenshots/ (``*_125.png`` / ``*_150.png``). It also checks
the layout: no visible widget may stick out past the view's right edge, and the view's
minimum width must fit the default 900 px window.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

from secretary.controller import Controller
from secretary.store.db import Connection, migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import inbox as inbox_repo
from secretary.store.repos import messages as messages_repo
from secretary.tools.email import email_send_prepare
from secretary.ui.theme import apply_theme
from secretary.ui.views.approvals import ApprovalsView
from secretary.ui.views.chat import ChatView
from secretary.ui.views.settings import SettingsView
from secretary.ui.views.tasks import TasksView
from secretary.ui.views.today import TodayView

OUT = Path("docs/screenshots")
WIDTH, HEIGHT = 900, 600


class _DummyConn:
    """Controller only stores the connection."""


def _conn() -> Connection:
    tmp = Path(tempfile.mkdtemp()) / "scale.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    return con


def _views() -> list[tuple[str, QWidget, Connection | None]]:
    out: list[tuple[str, QWidget, Connection | None]] = []

    con = _conn()
    controller = Controller(con)
    controller.create_task_manual("Buy groceries for the week and call the dentist", "")
    out.append(("tasks_with_item", TasksView(controller), con))

    con = _conn()
    controller = Controller(con)
    inbox_repo.create(con, kind="reminder", title="Take medicine", body="After breakfast.", turn_id="seed")
    controller.create_task_manual("File taxes", "")
    out.append(("today_with_items", TodayView(controller), con))

    con = _conn()
    messages_repo.create(
        con, from_addr="me@example.com", to_addrs='["newperson@example.com"]',
        subject="Review", body="Please review this.",
        received_at="2026-11-09T09:00:00+00:00", source="draft", turn_id="s")
    draft_id = messages_repo.create(
        con, from_addr="me@example.com", to_addrs='["newperson@example.com"]',
        subject="Review", body="Please review this.",
        received_at="2026-11-09T09:00:00+00:00", source="draft", turn_id="s")
    email_send_prepare(con, "t-1", {"draft_ref": str(draft_id)})
    out.append(("approvals_with_item", ApprovalsView(Controller(con)), con))

    out.append(("chat_empty", ChatView(Controller(_DummyConn())), None))
    out.append(("settings", SettingsView(Controller(_DummyConn())), None))
    return out


@pytest.mark.parametrize("scale", [1.25, 1.5])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_views_fit_at_scaled_text(scale: float, theme: str, tmp_path: Path) -> None:
    os.environ["SECRETARY_DATA_ROOT"] = str(tmp_path)
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    base_font = app.font()
    views = _views()
    try:
        apply_theme(app, theme)
        scaled = app.font()
        scaled.setPointSizeF(base_font.pointSizeF() * scale)
        app.setFont(scaled)

        for name, view, _con in views:
            view.resize(WIDTH, HEIGHT)
            view.show()
            app.processEvents()
            assert view.minimumSizeHint().width() <= WIDTH, (
                f"{name} needs {view.minimumSizeHint().width()} px at {scale:.0%}; the window starts at {WIDTH}"
            )
            for widget in view.findChildren(QWidget):
                if widget.isHidden() or not widget.isVisibleTo(view):
                    continue
                right = widget.mapTo(view, QPoint(widget.width(), 0)).x()
                # Scroll-area content may be wider than the viewport; only direct layout
                # children of the view (not widgets inside a scrolled list) must fit.
                if widget.parentWidget() is not None and widget.parentWidget().objectName() == "qt_scrollarea_viewport":
                    continue
                assert right <= WIDTH + 1, f"{name}: {type(widget).__name__} ends at {right} px (> {WIDTH}) at {scale:.0%}"
            path = OUT / f"{name}_{theme}_{round(scale * 100)}.png"
            assert view.grab().save(str(path)) and path.stat().st_size > 0
    finally:
        app.setFont(base_font)
        for _name, view, con in views:
            view.close()
            if con is not None:
                con.close()

"""Screenshot grabs for the UI review loop (plan §12, skill secretary-ui-design §7).

Grabs views in light and dark themes (offscreen QT_QPA_PLATFORM)
and saves PNGs under docs/screenshots/. Also runs the programmatic checks the
skill requires when images cannot be inspected directly: labels non-empty and
a cycling tab order.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from secretary.controller import Controller
from secretary.store.db import migrations_folder
from secretary.store.migrate import migrate
from secretary.store.repos import messages as messages_repo
from secretary.tools.email import email_send_prepare
from secretary.ui.theme import apply_theme
from secretary.ui.views.approvals import ApprovalsView
from secretary.ui.views.settings import SettingsView

OUT = Path("docs/screenshots")


class _DummyConn:
    """Controller only stores the connection."""


def _approvals_conn() -> sqlite3.Connection:
    tmp = Path(tempfile.mkdtemp()) / "ap.db"
    con = sqlite3.connect(str(tmp), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con, migrations_folder(), lambda: None)
    messages_repo.create(
        con, from_addr="me@example.com", to_addrs='["ravi@example.com"]',
        subject="Draft for ravi", body="Hello Ravi",
        received_at="2026-11-09T08:00:00+00:00", source="draft", turn_id="s")
    draft_id = messages_repo.create(
        con, from_addr="me@example.com", to_addrs='["newperson@example.com"]',
        subject="Review", body="Please review this.",
        received_at="2026-11-09T09:00:00+00:00", source="draft", turn_id="s")
    email_send_prepare(con, "t-1", {"draft_ref": str(draft_id)})
    return con


def _grab(app: QApplication, theme: str, view: QWidget, name: str) -> Path:
    apply_theme(app, theme)
    view.resize(900, 600)
    view.show()
    pix = view.grab()
    path = OUT / f"{name}_{theme}_100.png"
    assert pix.save(str(path))
    return path


def test_screenshots_and_checks() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    produced: list[Path] = []

    # Approvals view: empty state and with a pending email send.
    empty_view = ApprovalsView(Controller(_DummyConn()))
    for theme in ("light", "dark"):
        produced.append(_grab(app, theme, empty_view, "approvals_empty"))
    con = _approvals_conn()
    try:
        controller = Controller(con)
        item_view = ApprovalsView(controller)
        for theme in ("light", "dark"):
            produced.append(_grab(app, theme, item_view, "approvals_with_item"))
    finally:
        con.close()

    # Settings view.
    for theme in ("light", "dark"):
        produced.append(_grab(app, theme, SettingsView(Controller(_DummyConn())), "settings"))

    for path in produced:
        assert path.exists() and path.stat().st_size > 0, path

    # Programmatic checks (skill §7: no empty label text, cycling tab order).
    for view in (empty_view, item_view, SettingsView(Controller(_DummyConn()))):
        view.show()
        view.resize(900, 600)
        for widget in view.findChildren(QWidget):
            if widget.inherits("QLabel") and not widget.text():
                raise AssertionError(f"empty label text: {widget}")
        focusables = [w for w in view.findChildren(QWidget) if w.focusPolicy() & Qt.TabFocus]
        if focusables:
            first = focusables[0]
            current = first
            for _ in range(50):
                current = current.nextInFocusChain()
                if current is first:
                    break
            else:
                raise AssertionError("tab order chain does not cycle")

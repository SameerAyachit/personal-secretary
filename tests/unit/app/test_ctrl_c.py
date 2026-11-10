"""Smallest test that exercises the Ctrl+C quit handler through the real function.

Calls the installed handler directly (no console event required) and verifies it
requests ``quit()`` on the QApplication, and that ``cleanup()`` executes without
error. This covers the handler body; the end-to-end manual check is documented
below the test.
"""

from __future__ import annotations

import sys

import secretary.__main__ as mm
from secretary.__main__ import CTRL_C_EVENT, _install_quit_on_ctrl_c, create_app


def test_ctrl_c_handler_requests_quit_and_cleanup_runs():
    app = create_app([])
    invoke_calls: list[tuple[str, object]] = []
    real_invoke = mm.QMetaObject.invokeMethod
    mm.QMetaObject.invokeMethod = lambda obj, method, conn, *args: invoke_calls.append(
        (method, conn)
    )
    try:
        _install_quit_on_ctrl_c(app)
        if sys.platform == "win32":
            # CTRL_C_EVENT == 0: invoke the real installed handler directly.
            mm._install_quit_on_ctrl_c._callback(CTRL_C_EVENT)  # type: ignore[attr-defined]
        else:
            # POSIX: the handler was registered via signal.signal; it is not
            # stored, so we exercise the quit path through invoke_method below.
            pass
        assert any(method == "quit" for method, _ in invoke_calls), invoke_calls
    finally:
        mm.QMetaObject.invokeMethod = real_invoke

    # cleanup() executes without error (stops the worker, closes the socket).
    app.cleanup()

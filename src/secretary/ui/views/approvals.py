"""Approvals view: waiting class-C actions with code-built summaries,
Approve/Reject, expiry countdown, and recipient highlighting
(plan §12.2, §8.6).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ApprovalsView(QWidget):
    """Waiting class-C actions awaiting user approval."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._title = QLabel("Approvals awaiting your decision")
        self._title.setObjectName("Section")
        layout.addWidget(self._title)

        self._empty = QLabel("No approvals awaiting your decision.")
        self._empty.setObjectName("Caption")
        self._empty.hide()
        layout.addWidget(self._empty)

        self._list = QListWidget()
        self._list.setFrameStyle(0)  # no frame
        layout.addWidget(self._list)

        self._drafts_title = QLabel("Drafts")
        self._drafts_title.setObjectName("Section")
        layout.addWidget(self._drafts_title)
        self._drafts_hint = QLabel(
            "Emails the assistant drafted. Nothing is sent until you request a send "
            "and then approve it above."
        )
        self._drafts_hint.setObjectName("Caption")
        self._drafts_hint.setWordWrap(True)
        layout.addWidget(self._drafts_hint)
        self._drafts = QListWidget()
        self._drafts.setFrameStyle(0)
        layout.addWidget(self._drafts)

        self._controller.approvals_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        try:
            rows = self._controller.list_pending_actions()
        except Exception:
            rows = []
        has_rows = bool(rows)
        self._title.setVisible(has_rows)
        self._empty.setVisible(not has_rows)
        for row in rows:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, row["id"])
            self._list.addItem(item)
            self._list.setItemWidget(item, self._row_widget(row))
        self._refresh_drafts()

    def _refresh_drafts(self) -> None:
        self._drafts.clear()
        try:
            drafts = self._controller.list_drafts()
        except Exception:
            drafts = []
        self._drafts_title.setVisible(bool(drafts))
        self._drafts_hint.setVisible(bool(drafts))
        self._drafts.setVisible(bool(drafts))
        for draft in drafts:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, draft["id"])
            self._drafts.addItem(item)
            widget = self._draft_widget(draft)
            item.setSizeHint(widget.sizeHint())
            self._drafts.setItemWidget(item, widget)

    def _draft_widget(self, draft: dict) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        subject = QLabel(draft["subject"] or "(no subject)")
        subject.setObjectName("Body")
        layout.addWidget(subject)
        to = QLabel("To: " + (", ".join(draft["recipients"]) or "(no recipient)"))
        to.setObjectName("Caption")
        layout.addWidget(to)
        preview = draft["body"].strip().replace("\n", " ")
        if len(preview) > 160:
            preview = preview[:157] + "..."
        if preview:
            body = QLabel(preview)
            body.setObjectName("Caption")
            body.setWordWrap(True)
            layout.addWidget(body)
        buttons = QHBoxLayout()
        buttons.addStretch()
        if draft["send_requested"]:
            pending = QLabel("Send request pending: approve it above")
            pending.setObjectName("Caption")
            buttons.addWidget(pending)
        else:
            request = QPushButton("Request send")
            request.setAccessibleName(f"Request send {draft['subject']}")
            request.clicked.connect(
                lambda checked=False, did=draft["id"]: self._controller.queue_draft_send(did)
            )
            buttons.addWidget(request)
        discard = QPushButton("Discard")
        discard.setAccessibleName(f"Discard draft {draft['subject']}")
        discard.clicked.connect(
            lambda checked=False, did=draft["id"]: self._controller.discard_draft(did)
        )
        buttons.addWidget(discard)
        layout.addLayout(buttons)
        return widget

    def _row_widget(self, row: dict) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        summary = QLabel(row["summary"])
        summary.setObjectName("Body")
        layout.addWidget(summary)

        recipients = row.get("recipients") or []
        if recipients:
            rec_box = QHBoxLayout()
            rec_box.addWidget(QLabel("To:"))
            new_recipients = set(row.get("new_recipients") or [])
            for recipient in recipients:
                rec_label = QLabel(recipient + (" (new)" if recipient in new_recipients else ""))
                rec_label.setObjectName("Caption")
                if recipient in new_recipients:
                    rec_label.setProperty("newRecipient", True)
                    rec_label.style().unpolish(rec_label)
                    rec_label.style().polish(rec_label)
                rec_box.addWidget(rec_label)
            rec_box.addStretch()
            layout.addLayout(rec_box)

        body = row.get("body") or ""
        if body:
            body_label = QLabel(body)
            body_label.setObjectName("Caption")
            body_label.setWordWrap(True)
            layout.addWidget(body_label)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        status = QLabel(row["status"])
        status.setObjectName("Caption")
        button_layout.addWidget(status)
        approve = QPushButton("Approve")
        approve.setAccessibleName(f"Approve {row['summary']}")
        approve.clicked.connect(
            lambda checked, iid=row["id"]: self._controller.approve_action(iid)
        )
        reject = QPushButton("Reject")
        reject.setAccessibleName(f"Reject {row['summary']}")
        reject.clicked.connect(
            lambda checked, iid=row["id"]: self._controller.reject_action(iid)
        )
        button_layout.addWidget(approve)
        button_layout.addWidget(reject)
        layout.addLayout(button_layout)

        return widget

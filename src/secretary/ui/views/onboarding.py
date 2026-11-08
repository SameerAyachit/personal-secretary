"""First-run wizard (plan §6.4).

Walks the user through provider selection, API key storage in Credential Manager,
a "Test connection" step that discovers rate limits, timezone/quiet-hours/startup
settings, and optional Google connect. All core interactions go through the
Controller facade; the UI never touches store or LLM directly.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class OnboardingWizard(QDialog):
    """Multi-page first-run wizard."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller
        self.setWindowTitle("Welcome to Secretary")
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)

        self._stack = QStackedWidget()
        self._pages: list[QWidget] = []

        self._btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._btns.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)
        self._next_btn = QPushButton("Next")
        self._next_btn.setObjectName("Accent")
        self._next_btn.clicked.connect(self._next_page)
        self._btns.addButton(self._next_btn, QDialogButtonBox.ButtonRole.AcceptRole)

        layout = QVBoxLayout(self)
        layout.addWidget(self._stack)
        layout.addWidget(self._btns)

        self._build_pages()
        self._stack.setCurrentIndex(0)
        self._update_buttons()

    # ------------------------------------------------------------------ pages

    def _build_pages(self) -> None:
        self._pages = [
            self._welcome_page(),
            self._provider_page(),
            self._test_page(),
            self._general_page(),
            self._done_page(),
        ]
        for page in self._pages:
            self._stack.addWidget(page)

    def _welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addWidget(QLabel("Welcome to Secretary"))
        layout.addWidget(
            QLabel(
                "Secretary is your personal assistant on the desktop. It helps with "
                "tasks, reminders, planning, calendar, email triage and short research."
            )
        )
        layout.addWidget(
            QLabel(
                "Everything runs locally on your PC. Only the text you choose to send "
                "goes to your LLM provider, and secrets are stored in Windows Credential "
                "Manager, never in plain text."
            )
        )
        layout.addStretch()
        return page

    def _provider_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addWidget(QLabel("LLM provider"))
        layout.addWidget(
            QLabel("Choose an OpenAI-compatible provider and paste your API key.")
        )
        self._provider = QLineEdit("Groq")
        self._provider.setPlaceholderText("Groq")
        layout.addWidget(self._provider)
        self._base_url = QLineEdit("https://api.groq.com/openai/v1")
        self._base_url.setPlaceholderText("https://api.groq.com/openai/v1")
        layout.addWidget(self._base_url)
        self._model = QLineEdit("llama-3.1-8b-instant")
        self._model.setPlaceholderText("Model (e.g. llama-3.1-8b-instant)")
        layout.addWidget(self._model)
        self._key = QLineEdit()
        self._key.setPlaceholderText("Paste your API key")
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._key)
        layout.addStretch()
        return page

    def _test_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addWidget(QLabel("Test connection"))
        layout.addWidget(
            QLabel("Send a tiny request to your model to confirm the key works and discover rate limits.")
        )
        self._test_btn = QPushButton("Test connection")
        self._test_btn.setObjectName("Accent")
        self._test_btn.clicked.connect(self._run_test)
        layout.addWidget(self._test_btn)
        self._test_status = QLabel("")
        layout.addWidget(self._test_status)
        layout.addStretch()
        return page

    def _general_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addWidget(QLabel("General settings"))
        cfg = self._controller.get_config()
        self._tz = QLineEdit(cfg.get("timezone", "Asia/Kolkata"))
        self._tz.setPlaceholderText("Timezone (e.g. Asia/Kolkata)")
        layout.addWidget(self._tz)
        self._start_minimized = QCheckBox("Start minimized to tray")
        self._start_minimized.setChecked(bool(cfg.get("start_minimized", True)))
        layout.addWidget(self._start_minimized)
        layout.addStretch()
        return page

    def _done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        self._done_label = QLabel("Setup complete.")
        layout.addWidget(self._done_label)
        layout.addWidget(
            QLabel("Press the global hotkey (Ctrl+Alt+Space) to quick-capture from any app.")
        )
        layout.addWidget(
            QLabel("The Secretary icon lives in the system tray; Quit is the only way to exit.")
        )
        layout.addStretch()
        return page

    # ------------------------------------------------------------------ navigation

    def _next_page(self) -> None:
        idx = self._stack.currentIndex()
        if idx == 1:
            self._save_provider()
        elif idx == 2:
            return  # wait for test
        elif idx == 3:
            self._save_general()
        if idx < self._stack.count() - 1:
            self._stack.setCurrentIndex(idx + 1)
        self._update_buttons()

    def _update_buttons(self) -> None:
        idx = self._stack.currentIndex()
        self._next_btn.setVisible(idx < self._stack.count() - 1)
        self._next_btn.setText("Next" if idx < self._stack.count() - 1 else "Finish")
        self._next_btn.setEnabled(True)

    # ------------------------------------------------------------------ actions

    def _save_provider(self) -> None:
        provider = self._provider.text().strip() or "groq"
        base_url = self._base_url.text().strip() or "https://api.groq.com/openai/v1"
        model = self._model.text().strip() or "llama-3.1-8b-instant"
        key = self._key.text().strip()
        if not key:
            self._test_status.setText("Please paste an API key.")
            return
        self._controller.set_llm_provider(provider, key, base_url, model)
        self._next_page()

    def _run_test(self) -> None:
        base_url = self._base_url.text().strip() or "https://api.groq.com/openai/v1"
        model = self._model.text().strip() or "llama-3.1-8b-instant"
        key = self._key.text().strip()
        if not key:
            self._test_status.setText("Please paste an API key.")
            return
        self._test_btn.setEnabled(False)
        self._test_status.setText("Testing connection...")
        result = self._controller.test_llm_connection(base_url, key, model)
        self._on_test_result(result)

    def _on_test_result(self, result: dict) -> None:
        self._test_btn.setEnabled(True)
        if isinstance(result, dict) and "error" in result:
            self._test_status.setText(f"Connection failed: {result['error']}")
            return
        headers = result.get("headers", {})
        lines = [
            f"Connection OK — model {result.get('model')}",
            f"Latency: {result.get('latency_ms')} ms",
            f"Tokens: {result.get('total_tokens')} (prompt {result.get('prompt_tokens')}, "
            f"completion {result.get('completion_tokens')})",
        ]
        if headers:
            lines.append("Rate-limit headers:")
            for k, v in headers.items():
                lines.append(f"  {k}: {v}")
        self._test_status.setText("\n".join(lines))

    def _save_general(self) -> None:
        tz = self._tz.text().strip() or "Asia/Kolkata"
        self._controller.save_general(tz, self._start_minimized.isChecked())
        self._next_page()

    def accept(self) -> None:
        idx = self._stack.currentIndex()
        if idx == self._stack.count() - 1:
            super().accept()
        else:
            self._next_page()

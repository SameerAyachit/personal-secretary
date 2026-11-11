"""JSON-lines logging with a redaction filter (plan §16).

Secrets (API keys, tokens, refresh tokens) are never written to logs or SQLite.
Every log line is valid JSON produced by json.dumps on a record dict, so the
log file is always machine-parseable.
"""

from __future__ import annotations

import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler

# Secret-like key names whose dict values must be redacted in logs.
_SECRET_KEYS = frozenset({
    "api_key", "apikey", "secret", "token", "refresh_token", "access_token",
    "password", "passwd", "credentials", "authorization",
})

# Patterns for secret-like string values that should be redacted even when
# they appear as plain strings (not dict keys).
_SECRET_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),          # Groq API keys
    re.compile(r"AIza[0-9A-Za-z\\-]{35,}"),       # Google API keys
    re.compile(r"ya29\\.[0-9A-Za-z\\-]+"),        # Google OAuth tokens
    re.compile(r"[0-9A-Za-z\\-]{40,}"),           # Long generic tokens
]

_REDACTED = "[REDACTED]"


def _is_secret_key(key: str) -> bool:
    kl = str(key).lower()
    return any(s in kl for s in _SECRET_KEYS)


def _redact_value(value, key: str | None = None):
    """Redact a single value; secret-like strings are replaced."""
    if isinstance(value, dict):
        return _redact_obj(value, key)
    if isinstance(value, list):
        return _redact_obj(value, key)
    if isinstance(value, str):
        if key is not None and _is_secret_key(key):
            return _REDACTED
        for pat in _SECRET_PATTERNS:
            if pat.search(value):
                return _REDACTED
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return json.dumps(value, default=str)


def _redact_obj(obj, key: str | None = None):
    """Redact secret values in a JSON-serialisable structure."""
    if isinstance(obj, dict):
        return {k: _redact_obj(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_obj(v) for v in obj]
    return _redact_value(obj, key)


class _JsonFormatter(logging.Formatter):
    """Format each log record as a single JSON line via json.dumps."""

    def format(self, record: logging.LogRecord) -> str:
        record_dict = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            record_dict["exc_info"] = self.formatException(record.exc_info)
        # Redact secret-like values from the message.
        record_dict = _redact_obj(record_dict)
        return json.dumps(record_dict, default=str)


class RedactionFilter(logging.Filter):
    """Redacts secret-like values from log records and their args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(_redact_obj(a) for a in record.args)
        record.msg = _redact_value(record.msg)
        return True


def _log_dir() -> str:
    r"""Default data root lives under %LOCALAPPDATA%\Secretary (wired in Phase 1).
    Fall back to a logs folder next to the repo so logging works from line one.
    """
    base = os.environ.get("SECRETARY_DATA_ROOT") or os.path.join(os.path.expanduser("~"), ".secretary")
    return os.path.join(base, "logs")


def setup_logging(level: int = logging.INFO, log_file: str | None = None) -> logging.Logger:
    logger = logging.getLogger("secretary")
    logger.setLevel(level)
    logger.handlers.clear()

    formatter = _JsonFormatter()

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    sh.addFilter(RedactionFilter())
    logger.addHandler(sh)

    if log_file is None:
        log_file = os.path.join(_log_dir(), "secretary.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    fh = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(formatter)
    fh.addFilter(RedactionFilter())
    logger.addHandler(fh)

    logging.getLogger().addFilter(RedactionFilter())
    return logger

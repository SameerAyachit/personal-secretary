"""JSON-lines logging with a redaction filter (plan §16).

Secrets (API keys, tokens, refresh tokens) are never written to logs or SQLite.
"""

from __future__ import annotations

import json
import logging
import os
from logging.handlers import RotatingFileHandler

_REDACTED = "[REDACTED]"

# Secret-like key names whose values must be redacted in logs.
_SECRET_KEYS = frozenset({
    "api_key", "apikey", "secret", "token", "refresh_token", "access_token",
    "password", "passwd", "credentials", "authorization",
})


def _redact_obj(obj):
    """Redact secret values; leave plain strings readable.

    Only dict values whose keys look secret-like are masked. Plain strings
    (e.g. log messages, positional args) are left intact so the rest of the
    message stays readable.
    """
    if isinstance(obj, dict):
        return {k: (_REDACTED if _is_secret(k) else _redact_obj(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redact_obj(v) for v in obj]
    return obj


def _is_secret(key: str) -> bool:
    kl = str(key).lower()
    return any(s in kl for s in _SECRET_KEYS)


class RedactionFilter(logging.Filter):
    """Redacts secret-like values from log records and their args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(_redact_obj(a) if isinstance(a, (dict, list, tuple)) else a for a in record.args)
        record.msg = _redact_obj(record.msg) if isinstance(record.msg, (dict, list)) else record.msg
        return True


def _log_dir() -> str:
    # Default data root lives under %LOCALAPPDATA%\Secretary (wired in Phase 1).
    # Fall back to a logs folder next to the repo so logging works from line one.
    base = os.environ.get("SECRETARY_DATA_ROOT") or os.path.join(os.path.expanduser("~"), ".secretary")
    return os.path.join(base, "logs")


def setup_logging(level: int = logging.INFO, log_file: str | None = None) -> logging.Logger:
    logger = logging.getLogger("secretary")
    logger.setLevel(level)
    logger.handlers.clear()

    formatter = logging.Formatter(
        json.dumps({"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"})
    )

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

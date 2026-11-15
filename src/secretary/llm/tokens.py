"""Token counting with a vendored tiktoken cl100k_base (plan §7.4, concern C-14).

The ``cl100k_base`` encoding file is vendored in ``src/secretary/llm/vendor/``
so token counting works offline and inside the packaged PyInstaller app.
``TIKTOKEN_CACHE_DIR`` is pointed at that folder before tiktoken is imported.
Falls back to a conservative chars/3 estimate if tiktoken cannot load.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault(
    "TIKTOKEN_CACHE_DIR", str(Path(__file__).resolve().parent / "vendor")
)

import tiktoken

_ENCODING: tiktoken.Encoding | None
try:  # vendored encoding available offline and in the packaged app
    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODING = None


def count_tokens(text: str) -> int:
    """Count tokens in ``text``.

    Uses the vendored cl100k_base encoding when available; otherwise falls
    back to a conservative ``len(text) // 3`` estimate.
    """
    enc = _ENCODING
    if enc is not None:
        return len(enc.encode(text))
    return max(0, len(text) // 3)


def truncate_tokens(text: str, max_tokens: int) -> str:
    """The first ``max_tokens`` tokens of ``text`` (same fallback estimate as above)."""
    enc = _ENCODING
    if enc is not None:
        ids = enc.encode(text)
        return text if len(ids) <= max_tokens else enc.decode(ids[:max_tokens])
    return text[: max_tokens * 3]

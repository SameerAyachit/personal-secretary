"""Idempotency keys for tool calls (plan §8.3).

Each tool call gets an idempotency key = hash(turn_id, tool name, normalised
args). Retried calls within a turn return the previous result.
"""

from __future__ import annotations

import hashlib
import json


def idempotency_key(turn_id: str, tool_name: str, args: dict) -> str:
    """Stable, order-independent idempotency key for a tool call."""
    normalized = json.dumps(args, sort_keys=True, separators=(",", ":"))
    payload = f"{turn_id}|{tool_name}|{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

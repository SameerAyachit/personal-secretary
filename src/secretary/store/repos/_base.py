"""Shared helpers for store repositories."""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3


def now_utc() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def action_log(
    con: sqlite3.Connection,
    turn_id: str | None,
    event: str,
    entity: str,
    entity_id: int | None,
    detail: dict | None,
) -> None:
    con.execute(
        "INSERT INTO action_log(ts, event, entity, entity_id, turn_id, detail_json) "
        "VALUES(?,?,?,?,?,?)",
        (now_utc(), event, entity, entity_id, turn_id, json.dumps(detail) if detail is not None else None),
    )


def row_to_dict(cur: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    return {col[0]: row[idx] for idx, col in enumerate(cur.description)}

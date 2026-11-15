"""Tests for the redaction filter (plan §16 / secretary-ui-design skill §4).

Mask only secret values (API keys, tokens, client secrets); keep the rest of
the message readable. Plain string log messages must NOT be redacted.
"""
from __future__ import annotations

import logging

import secretary.logging_setup as ls


def _record(msg, args=()) -> logging.LogRecord:
    return logging.LogRecord("secretary", logging.INFO, "", 0, msg, args, None)


def test_redact_secret_dict_values():
    record = _record({"api_key": "sk-1234567890", "user": "alice"})
    ls.RedactionFilter().filter(record)
    assert record.msg == {"api_key": "[REDACTED]", "user": "alice"}, record.msg


def test_redact_secret_dict_value_nested():
    record = _record({"config": {"api_key": "sk-1234567890", "region": "us-east-1"}})
    ls.RedactionFilter().filter(record)
    assert record.msg == {"config": {"api_key": "[REDACTED]", "region": "us-east-1"}}, record.msg


def test_plain_string_message_not_redacted():
    record = _record("Processing user %s", ("alice",))
    ls.RedactionFilter().filter(record)
    assert record.msg == "Processing user %s"
    assert record.args == ("alice",)


def test_plain_text_message_not_redacted():
    record = _record("Scheduler fired reminder 'drink water'")
    ls.RedactionFilter().filter(record)
    assert record.msg == "Scheduler fired reminder 'drink water'"


def test_list_of_strings_not_redacted():
    record = _record(["sk-1234567890", "sk-9876543210"])
    ls.RedactionFilter().filter(record)
    assert record.msg == ["sk-1234567890", "sk-9876543210"], record.msg


def test_nvidia_api_key_in_message_is_redacted():
    # Shorter than the generic 40-char rule and containing '_': needs its own pattern.
    out = ls._redact_obj({"message": "auth failed for nvapi-ab_CD-ef1234567890XYZ"})
    assert out == {"message": "[REDACTED]"}

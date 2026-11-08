"""Tests for idempotency keys (plan §8.3)."""


from secretary.tools.idempotency import idempotency_key


def test_idempotency_key_deterministic():
    k1 = idempotency_key("turn-1", "task_create", {"title": "x", "when_text": "tomorrow"})
    k2 = idempotency_key("turn-1", "task_create", {"title": "x", "when_text": "tomorrow"})
    assert k1 == k2


def test_idempotency_key_differs_by_turn():
    assert idempotency_key("turn-1", "task_create", {"title": "x"}) != idempotency_key(
        "turn-2", "task_create", {"title": "x"}
    )


def test_idempotency_key_differs_by_tool():
    assert idempotency_key("turn-1", "task_create", {"title": "x"}) != idempotency_key(
        "turn-1", "reminder_create", {"title": "x"}
    )


def test_idempotency_key_differs_by_args():
    assert idempotency_key("turn-1", "task_create", {"title": "x"}) != idempotency_key(
        "turn-1", "task_create", {"title": "y"}
    )


def test_idempotency_key_order_independent():
    a = idempotency_key("turn-1", "task_create", {"title": "x", "when_text": "tomorrow"})
    b = idempotency_key("turn-1", "task_create", {"when_text": "tomorrow", "title": "x"})
    assert a == b

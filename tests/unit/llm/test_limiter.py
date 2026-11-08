"""Tests for llm/limiter.py: token-bucket rate limiter (plan §7.4)."""

import asyncio

import pytest

from secretary.llm.errors import RequestTooLarge
from secretary.llm.limiter import Limiter


def test_acquire_deducts_tokens():
    now = [0.0]
    lim = Limiter(rpm=60, tpm=600, safety=1.0, clock=lambda: now[0])
    asyncio.run(lim.acquire(100))
    assert lim.tok_tokens == 500
    assert lim.req_tokens == 59


def test_request_too_large_exceeds_bucket():
    now = [0.0]
    lim = Limiter(rpm=60, tpm=600, safety=1.0, clock=lambda: now[0])
    # tpm_cap = 600; a 700-token estimate exceeds the whole bucket.
    with pytest.raises(RequestTooLarge):
        asyncio.run(lim.acquire(700))


def test_request_too_large_never_waits():
    # C-9: must raise immediately, not loop forever.
    now = [0.0]
    calls = [0]
    def clock():
        calls[0] += 1
        return now[0]
    lim = Limiter(rpm=60, tpm=600, safety=1.0, clock=clock)
    with pytest.raises(RequestTooLarge):
        asyncio.run(lim.acquire(700))
    assert calls[0] == 1  # clock read once, no waiting loop


def test_refill_advances_with_clock():
    now = [0.0]
    lim = Limiter(rpm=60, tpm=600, safety=1.0, clock=lambda: now[0])
    lim.tok_tokens = 0
    now[0] += 30  # 30 seconds -> 300 tokens (600 per minute)
    lim._refill()
    assert lim.tok_tokens == 300


def test_refill_caps_at_bucket():
    now = [0.0]
    lim = Limiter(rpm=60, tpm=600, safety=1.0, clock=lambda: now[0])
    now[0] += 3600  # one hour -> would far exceed cap
    lim._refill()
    assert lim.tok_tokens == 600
    assert lim.req_tokens == 60


def test_reconcile_corrects_estimate():
    now = [0.0]
    lim = Limiter(rpm=60, tpm=600, safety=1.0, clock=lambda: now[0])
    asyncio.run(lim.acquire(100))  # tok 500
    lim.reconcile(used_tokens=90, est_tokens=100)
    assert lim.tok_tokens == 510  # 500 + (100 - 90)


def test_reconcile_drains_to_header():
    now = [0.0]
    lim = Limiter(rpm=60, tpm=600, safety=1.0, clock=lambda: now[0])
    asyncio.run(lim.acquire(100))  # tok 500
    lim.reconcile(used_tokens=0, est_tokens=100, header_remaining=100)
    assert lim.tok_tokens == 90  # min(600, 100*0.9)


@pytest.mark.asyncio
async def test_acquire_waits_then_refills(monkeypatch):
    now = [0.0]
    lim = Limiter(rpm=60, tpm=600, safety=1.0, clock=lambda: now[0])
    await lim.acquire(550)  # tok 50, req 59
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)
        now[0] += d

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await lim.acquire(550)  # waits ~50s to refill 500 tokens, then deducts
    assert lim.tok_tokens == 0
    assert len(sleeps) == 10  # 10 x 5s sleeps = 50s

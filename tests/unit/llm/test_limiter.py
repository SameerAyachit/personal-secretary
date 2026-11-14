"""Tests for llm/limiter.py: token-bucket rate limiter (plan §7.4)."""

import asyncio
from datetime import date

import pytest

from secretary.llm.errors import DailyLimitReached, RequestTooLarge
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


@pytest.mark.asyncio
async def test_interactive_served_before_background_when_both_wait(monkeypatch):
    # With an empty bucket, an interactive call and a background call both
    # wait; when tokens refill, the interactive call is served first
    # (concern C-53).
    now = [0.0]
    lim = Limiter(rpm=60, tpm=6000, safety=1.0, clock=lambda: now[0])
    lim.req_tokens = 0
    lim.tok_tokens = 0
    order = []

    orig_sleep = asyncio.sleep

    async def fake_sleep(d):
        now[0] += d  # time passes while sleeping
        await orig_sleep(0)  # yield control so the other call can run

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def interactive():
        await lim.acquire(100, priority="interactive")
        order.append("interactive")

    async def background():
        await lim.acquire(10, priority="background")
        order.append("background")

    await asyncio.gather(interactive(), background())
    assert order == ["interactive", "background"]


# ---- daily meters (plan §7.4: optional rpd/tpd, 0 = off) ----------------------------


def _daily(**kw):
    day = [date(2026, 11, 14)]
    lim = Limiter(
        rpm=kw.pop("rpm", 0), tpm=kw.pop("tpm", 0), safety=1.0, today=lambda: day[0], **kw
    )
    return lim, day


def test_daily_request_limit_raises_then_resets_next_day():
    lim, day = _daily(rpd=2)
    asyncio.run(lim.acquire(10))
    asyncio.run(lim.acquire(10))
    with pytest.raises(DailyLimitReached, match="daily"):
        asyncio.run(lim.acquire(10))
    day[0] = date(2026, 11, 15)
    asyncio.run(lim.acquire(10))  # new day, counters reset


def test_daily_token_limit_counts_estimates_and_reconciles():
    lim, _ = _daily(tpd=100)
    asyncio.run(lim.acquire(60))
    lim.reconcile(used_tokens=20, est_tokens=60)  # actual usage was lower
    asyncio.run(lim.acquire(70))  # 20 + 70 <= 100
    with pytest.raises(DailyLimitReached):
        asyncio.run(lim.acquire(20))


def test_minute_buckets_off_when_zero():
    lim, _ = _daily(rpd=5)  # rpm = tpm = 0: only the daily meter is active
    asyncio.run(lim.acquire(50_000))
    asyncio.run(lim.acquire(50_000))

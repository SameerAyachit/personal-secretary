"""Two-priority token-bucket rate limiter (plan §7.4).

Two priority classes share one token bucket:

* ``interactive`` -- chat turns and other user-facing work.
* ``background`` -- research briefs, triage, sync and other jobs.

An interactive call is always served as soon as the bucket allows. A background
call yields while an interactive call is waiting for tokens, so a long research
job can never stall a chat turn (plan §7.4, concern C-53).

If a single request's estimated tokens exceed the whole bucket,
:class:`RequestTooLarge` is raised immediately instead of waiting forever
(concern C-9). After each call, :meth:`reconcile` corrects the estimate from
actual usage and rate-limit headers.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, date, datetime

from .errors import DailyLimitReached, RequestTooLarge


def _utc_today() -> date:
    return datetime.now(UTC).date()


class Limiter:
    """Two-priority token-bucket limiter keyed to a single provider/model."""

    def __init__(
        self,
        rpm: float,
        tpm: float,
        safety: float = 0.7,
        clock: Callable[[], float] = time.monotonic,
        *,
        rpd: int = 0,
        tpd: int = 0,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        # A value of 0 switches that meter off (plan §6.2: unknown limits are 0).
        self.rpm_cap = rpm * safety
        self.tpm_cap = tpm * safety
        self.rpd_cap = rpd * safety
        self.tpd_cap = tpd * safety
        self._today = today
        self._day = today()
        self._day_requests = 0
        self._day_tokens = 0
        self.req_tokens = self.rpm_cap
        self.tok_tokens = self.tpm_cap
        self.last = clock()
        self.clock = clock
        # Number of interactive calls currently waiting for tokens. Background
        # calls yield while this is greater than zero.
        self._waiting_interactive = 0

    def _refill(self) -> None:
        now = self.clock()
        dt = now - self.last
        self.last = now
        self.req_tokens = min(self.rpm_cap, self.req_tokens + dt * self.rpm_cap / 60)
        self.tok_tokens = min(self.tpm_cap, self.tok_tokens + dt * self.tpm_cap / 60)

    def _wait_for(self, est_tokens: int) -> float:
        """Seconds until the enabled minute buckets fit ``est_tokens``."""
        waits = [0.25]
        if self.rpm_cap > 0:
            waits.append((1 - self.req_tokens) * 60 / self.rpm_cap)
        if self.tpm_cap > 0:
            waits.append((est_tokens - self.tok_tokens) * 60 / self.tpm_cap)
        return max(waits)

    def _roll_day(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self._day_requests = 0
            self._day_tokens = 0

    def _check_daily(self, est_tokens: int) -> None:
        self._roll_day()
        if self.rpd_cap > 0 and self._day_requests + 1 > self.rpd_cap:
            raise DailyLimitReached("The daily request limit for the AI provider is used up.")
        if self.tpd_cap > 0 and self._day_tokens + est_tokens > self.tpd_cap:
            raise DailyLimitReached("The daily token limit for the AI provider is used up.")

    async def acquire(
        self,
        est_tokens: int,
        *,
        priority: str = "background",
        on_wait: Callable[[float], None] | None = None,
    ) -> None:
        """Wait until the request fits in both buckets, then deduct.

        ``priority`` is ``"interactive"`` for chat turns or ``"background"``
        for research, triage and sync jobs. A background call yields while an
        interactive call is waiting for tokens.

        Raises :class:`RequestTooLarge` if ``est_tokens`` exceeds the whole
        token bucket (concern C-9).
        """
        if self.tpm_cap > 0 and est_tokens > self.tpm_cap:
            raise RequestTooLarge(
                f"estimated {est_tokens} tokens exceeds the whole bucket ({self.tpm_cap:.0f})"
            )
        self._check_daily(est_tokens)
        while True:
            self._refill()
            req_ok = self.rpm_cap <= 0 or self.req_tokens >= 1
            tok_ok = self.tpm_cap <= 0 or self.tok_tokens >= est_tokens
            if req_ok and tok_ok:
                if (
                    priority == "background"
                    and self._waiting_interactive > 0
                ):
                    # Yield: an interactive call is waiting to be served first.
                    wait = self._wait_for(est_tokens)
                    if on_wait is not None:
                        on_wait(wait)
                    await asyncio.sleep(min(wait, 5))
                    continue
                self.req_tokens -= 1
                self.tok_tokens -= est_tokens
                self._day_requests += 1
                self._day_tokens += est_tokens
                return
            wait = self._wait_for(est_tokens)
            if priority == "interactive":
                self._waiting_interactive += 1
            try:
                if on_wait is not None:
                    on_wait(wait)
                await asyncio.sleep(min(wait, 5))
            finally:
                if priority == "interactive":
                    self._waiting_interactive -= 1

    def reconcile(
        self,
        used_tokens: int,
        est_tokens: int,
        header_remaining: int | None = None,
    ) -> None:
        """Correct the bucket after a call from actual usage and headers."""
        self.tok_tokens += est_tokens - used_tokens
        self._day_tokens = max(0, self._day_tokens + used_tokens - est_tokens)
        if header_remaining is not None and self.tpm_cap > 0:
            try:
                remaining = int(header_remaining)
            except (TypeError, ValueError):
                remaining = None
            if remaining is not None:
                self.tok_tokens = min(self.tpm_cap, remaining * 0.9)

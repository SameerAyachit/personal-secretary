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

from .errors import RequestTooLarge


class Limiter:
    """Two-priority token-bucket limiter keyed to a single provider/model."""

    def __init__(
        self,
        rpm: float,
        tpm: float,
        safety: float = 0.7,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rpm_cap = rpm * safety
        self.tpm_cap = tpm * safety
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
        """Seconds until the bucket fits ``est_tokens``."""
        return max(
            (1 - self.req_tokens) * 60 / self.rpm_cap,
            (est_tokens - self.tok_tokens) * 60 / self.tpm_cap,
            0.25,
        )

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
        if est_tokens > self.tpm_cap:
            raise RequestTooLarge(
                f"estimated {est_tokens} tokens exceeds the whole bucket ({self.tpm_cap:.0f})"
            )
        while True:
            self._refill()
            if self.req_tokens >= 1 and self.tok_tokens >= est_tokens:
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
        if header_remaining is not None:
            try:
                remaining = int(header_remaining)
            except (TypeError, ValueError):
                remaining = None
            if remaining is not None:
                self.tok_tokens = min(self.tpm_cap, remaining * 0.9)

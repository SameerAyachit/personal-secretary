"""Token-bucket rate limiter (plan §7.4).

Two buckets: requests-per-minute and tokens-per-minute, each scaled by
``safety_factor``. If a single request's estimated tokens exceed the whole
bucket, :class:`RequestTooLarge` is raised immediately instead of waiting
forever (concern C-9). After each call, :meth:`reconcile` corrects the
estimate from actual usage and rate-limit headers.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from .errors import RequestTooLarge


class Limiter:
    """Async token-bucket limiter keyed to a single provider/model."""

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

    def _refill(self) -> None:
        now = self.clock()
        dt = now - self.last
        self.last = now
        self.req_tokens = min(self.rpm_cap, self.req_tokens + dt * self.rpm_cap / 60)
        self.tok_tokens = min(self.tpm_cap, self.tok_tokens + dt * self.tpm_cap / 60)

    async def acquire(self, est_tokens: int, *, on_wait: Callable[[float], None] | None = None) -> None:
        """Wait until the request fits in both buckets, then deduct.

        Raises :class:`RequestTooLarge`` if ``est_tokens`` exceeds the whole
        token bucket (concern C-9).
        """
        if est_tokens > self.tpm_cap:
            raise RequestTooLarge(
                f"estimated {est_tokens} tokens exceeds the whole bucket ({self.tpm_cap:.0f})"
            )
        while True:
            self._refill()
            if self.req_tokens >= 1 and self.tok_tokens >= est_tokens:
                self.req_tokens -= 1
                self.tok_tokens -= est_tokens
                return
            wait = max(
                (1 - self.req_tokens) * 60 / self.rpm_cap,
                (est_tokens - self.tok_tokens) * 60 / self.tpm_cap,
                0.25,
            )
            if on_wait is not None:
                on_wait(wait)
            await asyncio.sleep(min(wait, 5))

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
                self.tok_tokens = min(self.tok_tokens, remaining * 0.9)

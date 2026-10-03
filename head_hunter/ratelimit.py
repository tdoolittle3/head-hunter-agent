"""Per-user request limits.

The signed-in server is open to the internet and every message costs a Gemini
call, so one person (or one stolen token) must not be able to run up the bill.
This is the cheap, deterministic guard: a sliding window of timestamps per user,
checked before the agent runs.

It is per *instance*. Cloud Run may run several, each with its own memory, so the
real ceiling is the limit times ``--max-instances``. That is a deliberate trade:
a shared counter would need another service, and the instance cap already bounds
the worst case.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Sequence

SWEEP_AT = 10_000
"""Forget idle users once this many are tracked, so memory cannot grow forever."""


class RateLimiter:
    """Allow at most ``limit`` requests per ``window`` seconds, for each rule."""

    def __init__(
        self,
        rules: Sequence[tuple[int, float]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a limiter.

        Args:
            rules: ``(limit, window_seconds)`` pairs; a request must satisfy all.
            clock: Source of time in seconds. Injected so tests need no sleeping.
        """
        if not rules or any(limit < 1 or window <= 0 for limit, window in rules):
            raise ValueError("Every rate rule needs a positive limit and window.")
        self._rules = tuple(rules)
        self._longest = max(window for _, window in rules)
        self._clock = clock
        self._seen: dict[str, deque[float]] = {}

    def check(self, key: str) -> float:
        """Record a request, or say how long to wait.

        Returns:
            0.0 if the request is allowed (and is now counted), otherwise the
            number of seconds until it would be. A refused request is not counted.
        """
        now = self._clock()
        if len(self._seen) >= SWEEP_AT:
            self._sweep(now)
        stamps = self._seen.setdefault(key, deque())
        while stamps and now - stamps[0] >= self._longest:
            stamps.popleft()

        wait = 0.0
        for limit, window in self._rules:
            recent = [t for t in stamps if now - t < window]
            if len(recent) >= limit:
                wait = max(wait, recent[0] + window - now)
        if wait > 0:
            return wait
        stamps.append(now)
        return 0.0

    def _sweep(self, now: float) -> None:
        for key in [
            k for k, s in self._seen.items() if not s or now - s[-1] >= self._longest
        ]:
            del self._seen[key]

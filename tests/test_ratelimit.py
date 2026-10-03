"""The rate limit is the cost guard on a public Gemini endpoint.

It is tested with a fake clock rather than by sleeping.
"""

from __future__ import annotations

import pytest

from head_hunter import config
from head_hunter.ratelimit import SWEEP_AT, RateLimiter


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def test_requests_under_the_limit_pass(clock: Clock) -> None:
    limiter = RateLimiter([(3, 60)], clock)
    assert [limiter.check("a") for _ in range(3)] == [0.0, 0.0, 0.0]


def test_the_request_over_the_limit_is_told_how_long_to_wait(clock: Clock) -> None:
    limiter = RateLimiter([(2, 60)], clock)
    limiter.check("a")
    clock.now += 10
    limiter.check("a")
    clock.now += 5

    # The oldest request was 15s ago, so it frees up in 45s.
    assert limiter.check("a") == pytest.approx(45.0)


def test_a_refused_request_does_not_extend_the_wait(clock: Clock) -> None:
    limiter = RateLimiter([(1, 60)], clock)
    limiter.check("a")
    clock.now += 30
    for _ in range(5):
        limiter.check("a")

    clock.now += 30
    assert limiter.check("a") == 0.0


def test_the_window_slides_open_again(clock: Clock) -> None:
    limiter = RateLimiter([(1, 60)], clock)
    limiter.check("a")
    clock.now += 61
    assert limiter.check("a") == 0.0


def test_users_are_counted_separately(clock: Clock) -> None:
    limiter = RateLimiter([(1, 60)], clock)
    limiter.check("alice")
    assert limiter.check("alice") > 0
    assert limiter.check("bob") == 0.0


def test_every_rule_must_be_satisfied(clock: Clock) -> None:
    limiter = RateLimiter([(5, 60), (6, 3600)], clock)
    for _ in range(5):
        limiter.check("a")
        clock.now += 1
    clock.now += 60  # minute window clear again, hour window now holds 5

    assert limiter.check("a") == 0.0  # the 6th in the hour
    clock.now += 60
    assert limiter.check("a") > 0  # the 7th in the hour is over the daily-style cap


def test_idle_users_are_forgotten_so_memory_stays_bounded(clock: Clock) -> None:
    limiter = RateLimiter([(1, 60)], clock)
    for i in range(SWEEP_AT):
        limiter.check(f"user{i}")
    clock.now += 120
    limiter.check("someone-new")

    assert len(limiter._seen) < SWEEP_AT


@pytest.mark.parametrize("rules", [[], [(0, 60)], [(5, 0)], [(5, -1)]])
def test_nonsense_rules_are_refused(rules: list[tuple[int, float]]) -> None:
    with pytest.raises(ValueError):
        RateLimiter(rules)


def test_default_limits_exist_and_cannot_be_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HH_RATE_PER_MINUTE", raising=False)
    monkeypatch.delenv("HH_RATE_PER_DAY", raising=False)
    assert config.rate_limits() == [(10, 60.0), (200, 86_400.0)]

    for bad in ("0", "-3", "lots", "1.5"):
        monkeypatch.setenv("HH_RATE_PER_MINUTE", bad)
        with pytest.raises(ValueError, match="HH_RATE_PER_MINUTE"):
            config.rate_limits()

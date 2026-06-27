"""Tests for the sliding-window rate limiter."""

from __future__ import annotations

import pytest

from ledgerline_backend.security.rate_limit import SlidingWindowRateLimiter


def test_allows_up_to_the_limit() -> None:
    limiter = SlidingWindowRateLimiter(max_events=3, window_seconds=60)
    t = 1000.0
    for _ in range(3):
        assert limiter.is_blocked("ip", now=t) is False
        limiter.record("ip", now=t)
    assert limiter.is_blocked("ip", now=t) is True


def test_window_slides_and_unblocks() -> None:
    limiter = SlidingWindowRateLimiter(max_events=2, window_seconds=60)
    limiter.record("ip", now=100.0)
    limiter.record("ip", now=101.0)
    assert limiter.is_blocked("ip", now=102.0) is True
    # After the window passes, old events are evicted.
    assert limiter.is_blocked("ip", now=200.0) is False


def test_keys_are_independent() -> None:
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=60)
    limiter.record("a", now=10.0)
    assert limiter.is_blocked("a", now=10.0) is True
    assert limiter.is_blocked("b", now=10.0) is False


def test_reset_clears_a_key() -> None:
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=60)
    limiter.record("ip", now=10.0)
    assert limiter.is_blocked("ip", now=10.0) is True
    limiter.reset("ip")
    assert limiter.is_blocked("ip", now=10.0) is False


def test_invalid_configuration_rejected() -> None:
    with pytest.raises(ValueError, match="max_events"):
        SlidingWindowRateLimiter(max_events=0, window_seconds=60)
    with pytest.raises(ValueError, match="window_seconds"):
        SlidingWindowRateLimiter(max_events=1, window_seconds=0)

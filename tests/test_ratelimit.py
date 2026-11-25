"""Tests for ratelimit.py (section 12.4)."""

from __future__ import annotations

from stand_allocation.ratelimit import (
    AUTH_FAILURE_RULE,
    GENERAL_RULE,
    TokenBucketStore,
)


def test_clock_is_injected() -> None:
    """A fake clock drives the bucket; no real time is read."""
    store = TokenBucketStore()
    now = 1000.0
    allowed, remaining, _, _ = store.take("client-a", GENERAL_RULE, now)
    assert allowed is True
    assert remaining == 60 - 1
    allowed2, remaining2, _, _ = store.take("client-a", GENERAL_RULE, now)
    assert allowed2 is True
    assert remaining2 == 60 - 2


def test_auth_failure_bucket_retries() -> None:
    store = TokenBucketStore()
    now = 1000.0
    for _ in range(5):
        store.take("client-b", AUTH_FAILURE_RULE, now)
    assert store.available("client-b", AUTH_FAILURE_RULE, now) < 1.0

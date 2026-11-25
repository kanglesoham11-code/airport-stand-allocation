"""Token-bucket rate limiting (section 10A.2).

Two independent stores: GENERAL (per client IP) and AUTH_FAILURE (per client IP
for wrong/missing keys). Each bucket holds at most `capacity` tokens and
refills at `refill_per_second` tokens. Every counted request takes one token.
The whole call runs under a per-store lock.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from math import ceil, floor
from threading import Lock

from stand_allocation import config

RATE_EPSILON = config.RATE_EPSILON


@dataclass(frozen=True)
class RateRule:
    capacity: int
    refill_per_second: float


GENERAL_RULE = RateRule(config.RATE_LIMIT_CAPACITY, config.RATE_LIMIT_REFILL_PER_SECOND)
AUTH_FAILURE_RULE = RateRule(
    config.AUTH_FAILURE_CAPACITY, config.AUTH_FAILURE_REFILL_PER_SECOND
)


def ceil_seconds(x: float) -> int:
    """Ceil to whole seconds, absorbing floating-point rounding."""
    return ceil(x - RATE_EPSILON)


class TokenBucketStore:
    """LRU-bounded token bucket store. One lock covers the whole take() call."""

    def __init__(self, max_keys: int = config.RATE_LIMIT_MAX_KEYS) -> None:
        self._store: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = Lock()
        self._max_keys = max_keys

    def take(self, key: str, rule: RateRule, now: float) -> tuple[bool, int, int, int]:
        """Return (allowed, remaining_tokens, reset_seconds, retry_seconds)."""
        with self._lock:
            tokens, last = self._store.get(key, (rule.capacity, now))
            tokens = min(rule.capacity, tokens + (now - last) * rule.refill_per_second)
            allowed = tokens >= 1.0 - RATE_EPSILON
            if allowed:
                tokens -= 1.0
            self._store[key] = (tokens, now)  # save the time even when denied
            self._store.move_to_end(key)  # mark as recently used
            if len(self._store) > self._max_keys:
                self._store.popitem(last=False)  # drop least recently used

            remaining = max(0, floor(tokens + RATE_EPSILON))
            reset = ceil_seconds((rule.capacity - tokens) / rule.refill_per_second)
            retry = 0 if allowed else max(1, ceil_seconds((1.0 - tokens) / rule.refill_per_second))
            return allowed, remaining, reset, retry

    def available(self, key: str, rule: RateRule, now: float) -> float:
        """Peek at the current token count without consuming or saving state."""
        with self._lock:
            tokens, last = self._store.get(key, (rule.capacity, now))
            return min(rule.capacity, tokens + (now - last) * rule.refill_per_second)

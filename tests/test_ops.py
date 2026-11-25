"""Tests for ops.py (section 12.4)."""

from __future__ import annotations

from stand_allocation.ops import p95_nearest_rank


def test_p95_nearest_rank() -> None:
    assert p95_nearest_rank(list(range(1, 101))) == 95.0
    assert p95_nearest_rank(list(range(1, 1001))) == 950.0
    assert p95_nearest_rank([]) == 0.0

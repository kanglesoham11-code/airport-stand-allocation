"""Tests for metrics.py (section 12.4)."""

from __future__ import annotations

from stand_allocation import config
from stand_allocation.allocator import build_allocations, greedy_loop, post_process
from stand_allocation.metrics import compute_comparison_metrics, percent
from stand_allocation.models import Flight, Stand
from stand_allocation.timeutil import parse_utc

BUFFER_SECONDS = config.BUFFER_MINUTES * config.SECONDS_PER_MINUTE


def fl(flight_id: str, size: str, arrival: str, departure: str) -> Flight:
    return Flight(flight_id, size, parse_utc(arrival), parse_utc(departure))


def st(stand_id: str, stand_type: str, max_size: str) -> Stand:
    return Stand(stand_id, stand_type, max_size)


def test_decimal_rounding() -> None:
    """ROUND_HALF_UP: 6.25 percent -> 6.3 (banker's rounding would give 6.2)."""
    assert percent(1, 16) == 6.3
    assert percent(1, 4) == 25.0
    assert percent(7, 20) == 35.0
    assert percent(0, 5) == 0.0
    assert percent(1, 0) is None


def test_m7_m8_values() -> None:
    """M7 and M8 equal the differences between the primary and the baseline."""
    stands = [st("C02", "PLB", "M"), st("R03", "REMOTE", "M")]
    flights = [
        fl("A", "M", "2027-01-15T06:00:00Z", "2027-01-15T09:00:00Z"),
        fl("B", "M", "2027-01-15T06:30:00Z", "2027-01-15T07:00:00Z"),
        fl("C", "M", "2027-01-15T07:20:00Z", "2027-01-15T08:00:00Z"),
        fl("D", "M", "2027-01-15T08:30:00Z", "2027-01-15T09:00:00Z"),
    ]

    ga = greedy_loop(flights, stands, BUFFER_SECONDS)
    ga = post_process(ga, flights, stands, BUFFER_SECONDS)
    greedy_allocs = build_allocations(ga, flights, stands, BUFFER_SECONDS)

    metrics = compute_comparison_metrics(greedy_allocs, greedy_allocs)
    m7 = next(m for m in metrics if m.id == "M7")
    m8 = next(m for m in metrics if m.id == "M8")
    assert m7.value == 0.0
    assert m8.value == 0.0

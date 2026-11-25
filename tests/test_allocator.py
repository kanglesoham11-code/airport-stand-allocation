"""Tests for allocator.py (section 12.4)."""

from __future__ import annotations

import pytest

from stand_allocation import config
from stand_allocation.allocator import (
    AllocationInvariantError,
    build_allocations,
    conflicts,
    post_process,
)
from stand_allocation.models import Flight, Stand
from stand_allocation.timeutil import parse_utc

BUFFER_SECONDS = config.BUFFER_MINUTES * config.SECONDS_PER_MINUTE


def fl(flight_id: str, size: str, arrival: str, departure: str) -> Flight:
    return Flight(flight_id, size, parse_utc(arrival), parse_utc(departure))


def st(stand_id: str, stand_type: str, max_size: str) -> Stand:
    return Stand(stand_id, stand_type, max_size)


def test_buffer_in_seconds() -> None:
    """A next arrival exactly 15 minutes after a departure is allowed; 14:59 is not."""
    a = fl("A", "M", "2027-01-15T06:00:00Z", "2027-01-15T08:00:00Z")
    b_on_time = fl("B", "M", "2027-01-15T08:15:00Z", "2027-01-15T09:00:00Z")
    b_early = fl("B2", "M", "2027-01-15T08:14:59Z", "2027-01-15T09:00:00Z")
    assert not conflicts(a, b_on_time, BUFFER_SECONDS)
    assert conflicts(a, b_early, BUFFER_SECONDS)


def test_fill_places_free_flight() -> None:
    """An unassigned flight with a free compatible stand is placed by the fill step."""
    stands = [st("R03", "REMOTE", "M")]
    flights = [fl("X", "M", "2027-01-15T06:00:00Z", "2027-01-15T06:30:00Z")]
    assignments = {"X": None}
    assignments = post_process(assignments, flights, stands, BUFFER_SECONDS)
    assert assignments["X"] == "R03"
    allocs = build_allocations(assignments, flights, stands, BUFFER_SECONDS)
    assert allocs[0].status == "ASSIGNED"
    assert allocs[0].stand_id == "R03"


def test_upgrade_moves_remote_to_free_plb() -> None:
    """An assigned remote flight with a free compatible PLB stand moves to it."""
    stands = [st("C02", "PLB", "M"), st("R03", "REMOTE", "M")]
    flights = [fl("A", "M", "2027-01-15T06:00:00Z", "2027-01-15T07:00:00Z")]
    assignments = {"A": "R03"}
    assignments = post_process(assignments, flights, stands, BUFFER_SECONDS)
    assert assignments["A"] == "C02"
    allocs = build_allocations(assignments, flights, stands, BUFFER_SECONDS)
    assert allocs[0].stand_id == "C02"
    assert allocs[0].note is None  # PLB stand has no remote note


def test_unassigned_with_free_stand_raises_invariant() -> None:
    """An unassigned flight with a free compatible stand must not happen."""
    stands = [st("R03", "REMOTE", "M")]
    flights = [fl("X", "M", "2027-01-15T06:00:00Z", "2027-01-15T06:30:00Z")]
    assignments = {"X": None}
    with pytest.raises(AllocationInvariantError):
        build_allocations(assignments, flights, stands, BUFFER_SECONDS)

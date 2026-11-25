"""Allocation: greedy baseline and the shared fit/conflict/reason logic.

The greedy loop is the baseline (section 9.4). The fill step, the PLB upgrade
step and the unassigned reasons (section 9.4B) are shared by both candidates
so that the primary and the baseline are compared fairly (section 9.4B).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from stand_allocation import config
from stand_allocation.models import Allocation, Flight, Stand

REASON_TIME_FORMAT = "%H:%M UTC"


class AllocationInvariantError(Exception):
    """Raised when the allocation violates a rule that should be impossible."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def fits(flight: Flight, stand: Stand) -> bool:
    """True when the stand is big enough for the flight's aircraft (R2)."""
    return config.SIZE_RANK[stand.max_size] >= config.SIZE_RANK[flight.aircraft_size]


def conflicts(a: Flight, b: Flight, buffer_seconds: int) -> bool:
    """True when two flights cannot share a stand (section 9.2).

    A stand is occupied on the half-open interval
    [arrival, departure + buffer). Intervals that touch at one point do not
    conflict, because the end is excluded.
    """
    return (
        a.arrival < b.departure + timedelta(seconds=buffer_seconds)
        and b.arrival < a.departure + timedelta(seconds=buffer_seconds)
    )


def is_free(
    candidate: Flight,
    booked: list[Flight],
    buffer_seconds: int,
) -> bool:
    """True when the candidate does not conflict with any booked flight."""
    return not any(conflicts(candidate, other, buffer_seconds) for other in booked)


def best_free_stand(
    flight: Flight,
    compatible: list[Stand],
    booked: dict[str, list[Flight]],
    buffer_seconds: int,
) -> Stand | None:
    """Choose the best free stand: PLB first, then smallest fit, then id."""
    free = [
        stand
        for stand in compatible
        if is_free(flight, booked[stand.stand_id], buffer_seconds)
    ]
    if not free:
        return None
    return min(
        free,
        key=lambda stand: (
            config.STAND_TYPE_RANK[stand.stand_type],
            config.SIZE_RANK[stand.max_size],
            stand.stand_id,
        ),
    )


def compatible_stands(flight: Flight, stands: list[Stand]) -> list[Stand]:
    """Stands that fit the flight, sorted by stand_id for determinism."""
    return sorted(
        (stand for stand in stands if fits(flight, stand)), key=lambda s: s.stand_id
    )


@dataclass
class _Booking:
    """Mutable scratch state used while building one candidate."""

    assignments: dict[str, str | None]  # flight_id -> stand_id or None
    booked: dict[str, list[Flight]]  # stand_id -> flights on that stand

    def assign(self, flight: Flight, stand: Stand) -> None:
        self.assignments[flight.flight_id] = stand.stand_id
        self.booked[stand.stand_id].append(flight)

    def unassign(self, flight: Flight) -> None:
        stand_id = self.assignments.get(flight.flight_id)
        if stand_id is None:
            return
        self.assignments[flight.flight_id] = None
        self.booked[stand_id] = [
            f for f in self.booked[stand_id] if f.flight_id != flight.flight_id
        ]


def greedy_loop(
    flights: list[Flight], stands: list[Stand], buffer_seconds: int
) -> dict[str, str | None]:
    """Most-constrained-first greedy (section 9.4, steps 1-4).

    Returns flight_id -> stand_id or None. Reasons are computed later from the
    final state (section 9.4B step 6), so unassigned flights have no reason here.
    """
    compat = {f.flight_id: compatible_stands(f, stands) for f in flights}
    order = sorted(
        flights, key=lambda f: (len(compat[f.flight_id]), f.arrival, f.flight_id)
    )
    booking = _Booking(
        assignments={f.flight_id: None for f in flights},
        booked={s.stand_id: [] for s in stands},
    )
    for flight in order:
        stand = best_free_stand(flight, compat[flight.flight_id], booking.booked, buffer_seconds)
        if stand is not None:
            booking.assign(flight, stand)
    return booking.assignments


def post_process(
    assignments: dict[str, str | None],
    flights: list[Flight],
    stands: list[Stand],
    buffer_seconds: int,
) -> dict[str, str | None]:
    """Fill, PLB upgrade, fill again (section 9.4B steps 2-4).

    Runs on both candidates so the comparison is fair.
    """
    booking = _Booking(
        assignments=dict(assignments),
        booked={s.stand_id: [] for s in stands},
    )
    for flight in flights:
        booking.assignments.setdefault(flight.flight_id, None)
    for flight in flights:
        stand_id = booking.assignments.get(flight.flight_id)
        if stand_id is not None:
            booking.booked[stand_id].append(flight)

    compat = {f.flight_id: compatible_stands(f, stands) for f in flights}
    stands_by_id = {s.stand_id: s for s in stands}

    # Step 2: fill unassigned flights.
    unassigned = sorted(
        (f for f in flights if booking.assignments.get(f.flight_id) is None),
        key=lambda f: (f.arrival, f.flight_id),
    )
    for flight in unassigned:
        stand = best_free_stand(flight, compat[flight.flight_id], booking.booked, buffer_seconds)
        if stand is not None:
            booking.assign(flight, stand)

    # Step 3: PLB upgrade for remote flights.
    remote_assigned: list[Flight] = []
    for flight in flights:
        stand_id = booking.assignments.get(flight.flight_id)
        if stand_id is not None and stands_by_id[stand_id].stand_type == "REMOTE":
            remote_assigned.append(flight)
    remote_assigned.sort(key=lambda f: (f.arrival, f.flight_id))
    for flight in remote_assigned:
        current = booking.assignments[flight.flight_id]
        assert current is not None
        booking.unassign(flight)
        plb_stands = [s for s in compat[flight.flight_id] if s.stand_type == "PLB"]
        stand = best_free_stand(flight, plb_stands, booking.booked, buffer_seconds)
        if stand is not None:
            booking.assign(flight, stand)
        else:
            booking.assign(flight, stands_by_id[current])

    # Step 4: fill again (the upgrade may have freed a remote stand).
    unassigned = sorted(
        (f for f in flights if booking.assignments.get(f.flight_id) is None),
        key=lambda f: (f.arrival, f.flight_id),
    )
    for flight in unassigned:
        stand = best_free_stand(flight, compat[flight.flight_id], booking.booked, buffer_seconds)
        if stand is not None:
            booking.assign(flight, stand)

    return booking.assignments


def _reason_text(
    flight: Flight,
    compatible: list[Stand],
    booked: dict[str, list[Flight]],
    buffer_seconds: int,
) -> tuple[str, str, tuple[str, ...]]:
    """Build the unassigned reason from the final state (section 23.23)."""
    if not compatible:
        code = "NO_STAND_FOR_SIZE"
        text = (
            f"No stand in the airport can take a {flight.aircraft_size} aircraft."
        )
        return code, text, ()

    blockers: list[str] = []
    for stand in compatible:
        for other in booked[stand.stand_id]:
            if conflicts(flight, other, buffer_seconds):
                blockers.append(other.flight_id)
    blockers = sorted(set(blockers))

    if not blockers:
        raise AllocationInvariantError(
            f"flight {flight.flight_id} is unassigned but no compatible stand blocks it; "
            f"the fill step should have placed it"
        )

    code = "NO_FREE_COMPATIBLE_STAND"
    shown = blockers[: config.MAX_BLOCKED_BY_SHOWN]
    if len(blockers) > config.MAX_BLOCKED_BY_SHOWN:
        shown_text = ", ".join(shown) + f" and {len(blockers) - config.MAX_BLOCKED_BY_SHOWN} more"
    else:
        shown_text = ", ".join(shown)
    text = (
        f"All {len(compatible)} stands that can take size "
        f"{flight.aircraft_size} aircraft are busy between "
        f"{_reason_time(flight.arrival)} and {_reason_time(flight.departure)} UTC, "
        f"including the {config.BUFFER_MINUTES}-minute buffer. "
        f"Blocked by: {shown_text}."
    )
    return code, text, tuple(blockers)


def _reason_time(value: datetime) -> str:
    return value.strftime(REASON_TIME_FORMAT)


def build_allocations(
    assignments: dict[str, str | None],
    flights: list[Flight],
    stands: list[Stand],
    buffer_seconds: int,
) -> tuple[Allocation, ...]:
    """Build Allocation records with reasons and notes from a final state.

    Section 23.23 (reasons) and 23.24 (remote notes). Sorted by (arrival, flight_id).
    """
    booked: dict[str, list[Flight]] = {s.stand_id: [] for s in stands}
    stands_by_id = {s.stand_id: s for s in stands}
    for flight in flights:
        stand_id = assignments.get(flight.flight_id)
        if stand_id is not None:
            booked[stand_id].append(flight)

    records: list[Allocation] = []
    for flight in flights:
        stand_id = assignments.get(flight.flight_id)
        if stand_id is None:
            compatible = compatible_stands(flight, stands)
            code, text, blocked_by = _reason_text(
                flight, compatible, booked, buffer_seconds
            )
            records.append(
                Allocation(
                    flight_id=flight.flight_id,
                    aircraft_size=flight.aircraft_size,
                    arrival=flight.arrival,
                    departure=flight.departure,
                    status="UNASSIGNED",
                    stand_id=None,
                    stand_type=None,
                    note=None,
                    reason_code=code,
                    reason=text,
                    blocked_by=blocked_by,
                )
            )
        else:
            stand = stands_by_id[stand_id]
            note = (
                "No compatible PLB stand was free for this flight."
                if stand.stand_type == "REMOTE"
                else None
            )
            records.append(
                Allocation(
                    flight_id=flight.flight_id,
                    aircraft_size=flight.aircraft_size,
                    arrival=flight.arrival,
                    departure=flight.departure,
                    status="ASSIGNED",
                    stand_id=stand.stand_id,
                    stand_type=stand.stand_type,
                    note=note,
                    reason_code=None,
                    reason=None,
                    blocked_by=(),
                )
            )

    return tuple(sorted(records, key=lambda r: (r.arrival, r.flight_id)))

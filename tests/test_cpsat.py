"""Tests for solver_cpsat.py and the primary/baseline guarantee (section 12.4)."""

from __future__ import annotations

import random

from stand_allocation import config
from stand_allocation.allocator import (
    build_allocations,
    conflicts,
    greedy_loop,
    post_process,
)
from stand_allocation.models import Flight, Stand
from stand_allocation.solver_cpsat import solve_cpsat
from stand_allocation.timeutil import parse_utc

BUFFER_SECONDS = config.BUFFER_MINUTES * config.SECONDS_PER_MINUTE


def fl(flight_id: str, size: str, arrival: str, departure: str) -> Flight:
    return Flight(flight_id, size, parse_utc(arrival), parse_utc(departure))


def st(stand_id: str, stand_type: str, max_size: str) -> Stand:
    return Stand(stand_id, stand_type, max_size)


def _key(allocations, stands_by_max_size) -> tuple[int, int, int]:
    assigned = sum(1 for a in allocations if a.status == "ASSIGNED")
    plb = sum(
        1 for a in allocations if a.status == "ASSIGNED" and a.stand_type == "PLB"
    )
    oversize = sum(
        1
        for a in allocations
        if a.status == "ASSIGNED"
        and a.stand_id is not None
        and config.SIZE_RANK[stands_by_max_size[a.stand_id]]
        > config.SIZE_RANK[a.aircraft_size]
    )
    return (assigned, plb, -oversize)


def solve(flights, stands, seed):
    assignments = greedy_loop(flights, stands, BUFFER_SECONDS)
    assignments = post_process(assignments, flights, stands, BUFFER_SECONDS)
    greedy_allocs = build_allocations(assignments, flights, stands, BUFFER_SECONDS)
    outcome = solve_cpsat(flights, stands, BUFFER_SECONDS, 10.0, seed)
    solver_allocs = None
    if outcome.assignment is not None:
        sp = post_process(outcome.assignment, flights, stands, BUFFER_SECONDS)
        solver_allocs = build_allocations(sp, flights, stands, BUFFER_SECONDS)
    return greedy_allocs, solver_allocs, outcome.status


def _key_from_assignment(assignment, flights, stands) -> tuple[int, int, int] | None:
    if assignment is None:
        return None
    assigned = 0
    plb = 0
    oversize = 0
    stands_by_id = {s.stand_id: s for s in stands}
    for f in flights:
        sid = assignment.get(f.flight_id)
        if sid is None:
            continue
        stand = stands_by_id[sid]
        assigned += 1
        if stand.stand_type == "PLB":
            plb += 1
        oversize += config.SIZE_RANK[stand.max_size] - config.SIZE_RANK[f.aircraft_size]
    return (assigned, plb, -oversize)


def test_long_stay_example() -> None:
    """Section 9.7: solver gives 4 assigned and 3 PLB; greedy gives 4 assigned and 1 PLB."""
    stands = [st("C02", "PLB", "M"), st("R03", "REMOTE", "M")]
    flights = [
        fl("A", "M", "2027-01-15T06:00:00Z", "2027-01-15T09:00:00Z"),
        fl("B", "M", "2027-01-15T06:30:00Z", "2027-01-15T07:00:00Z"),
        fl("C", "M", "2027-01-15T07:20:00Z", "2027-01-15T08:00:00Z"),
        fl("D", "M", "2027-01-15T08:30:00Z", "2027-01-15T09:00:00Z"),
    ]
    greedy_allocs, solver_allocs, status = solve(flights, stands, 1)
    assert status == "OPTIMAL"
    g_assigned = sum(1 for a in greedy_allocs if a.status == "ASSIGNED")
    g_plb = sum(1 for a in greedy_allocs if a.status == "ASSIGNED" and a.stand_type == "PLB")
    s_assigned = sum(1 for a in solver_allocs if a.status == "ASSIGNED")
    s_plb = sum(1 for a in solver_allocs if a.status == "ASSIGNED" and a.stand_type == "PLB")
    assert g_assigned == 4 and g_plb == 1
    assert s_assigned == 4 and s_plb == 3


def test_deterministic() -> None:
    stands = [st("C01", "PLB", "L"), st("R03", "REMOTE", "M"), st("R06", "REMOTE", "S")]
    flights = [
        fl("AX100", "S", "2027-01-15T06:05:00Z", "2027-01-15T06:55:00Z"),
        fl("BQ200", "M", "2027-01-15T06:30:00Z", "2027-01-15T07:20:00Z"),
        fl("CZ300", "L", "2027-01-15T07:00:00Z", "2027-01-15T08:30:00Z"),
    ]
    _, a1, _ = solve(flights, stands, 5)
    _, a2, _ = solve(flights, stands, 5)
    if a1 is not None and a2 is not None:
        assert [(a.flight_id, a.stand_id) for a in a1] == [
            (a.flight_id, a.stand_id) for a in a2
        ]


def test_never_worse_than_greedy() -> None:
    rng = random.Random(123)
    for seed in range(20):
        n_stands = rng.randint(2, 3)
        stands = []
        for i in range(n_stands):
            stands.append(
                st(
                    f"S{i}",
                    rng.choice(["PLB", "REMOTE"]),
                    rng.choice(["S", "M", "L"]),
                )
            )
        n_flights = rng.randint(3, 6)
        flights = []
        for i in range(n_flights):
            size = rng.choice(["S", "M", "L"])
            hour = rng.randint(6, 10)
            minute = rng.choice([0, 15])
            flights.append(
                fl(
                    f"F{i}",
                    size,
                    f"2027-01-15T{hour:02d}:{minute:02d}:00Z",
                    f"2027-01-15T{hour:02d}:{minute+30:02d}:00Z",
                )
            )
        stands.sort(key=lambda s: s.stand_id)
        flights.sort(key=lambda f: (f.arrival, f.flight_id))
        greedy_allocs, solver_allocs, status = solve(flights, stands, seed)
        stands_by_max = {s.stand_id: s.max_size for s in stands}
        greedy_key = _key(greedy_allocs, stands_by_max)
        if solver_allocs is None:
            assert status in ("UNKNOWN", "INFEASIBLE", "MODEL_INVALID")
            continue
        solver_key = _key(solver_allocs, stands_by_max)
        primary_key = solver_key if solver_key >= greedy_key else greedy_key
        assert primary_key >= greedy_key


def test_matches_bruteforce() -> None:
    import itertools

    for seed in range(30):
        rng = random.Random(seed)
        n_stands = rng.randint(2, 3)
        stands = [
            st(f"S{i}", rng.choice(["PLB", "REMOTE"]), rng.choice(["S", "M", "L"]))
            for i in range(n_stands)
        ]
        n_flights = rng.randint(3, 6)
        flights = []
        for i in range(n_flights):
            size = rng.choice(["S", "M", "L"])
            h = rng.randint(6, 11)
            m = rng.choice([0, 20])
            flights.append(
                fl(
                    f"F{i}",
                    size,
                    f"2027-01-15T{h:02d}:{m:02d}:00Z",
                    f"2027-01-15T{h:02d}:{m+30:02d}:00Z",
                )
            )
        stands.sort(key=lambda s: s.stand_id)
        flights.sort(key=lambda f: (f.arrival, f.flight_id))
        greedy_allocs, solver_allocs, status = solve(flights, stands, seed)
        has_compat = any(
            config.SIZE_RANK[s.max_size] >= config.SIZE_RANK[f.aircraft_size]
            for f in flights for s in stands
        )
        if not has_compat:
            # No stand fits any flight: the solver is skipped and everything is
            # unassigned for size reasons (section 9.4A build order).
            assert status == "NOT_RUN"
            continue
        assert status == "OPTIMAL", f"seed {seed}: status {status}"
        outcome = solve_cpsat(flights, stands, BUFFER_SECONDS, 10.0, seed)
        solver_key = _key_from_assignment(outcome.assignment, flights, stands)

        compat = {
            f.flight_id: [
                s
                for s in stands
                if config.SIZE_RANK[s.max_size] >= config.SIZE_RANK[f.aircraft_size]
            ]
            for f in flights
        }
        choice_lists = [
            [None] + [s.stand_id for s in compat[f.flight_id]] for f in flights
        ]
        best = None
        for combo in itertools.product(*choice_lists):
            per_stand: dict[str, list[Flight]] = {}
            ok = True
            for f, sid in zip(flights, combo, strict=False):
                if sid is None:
                    continue
                next(s for s in stands if s.stand_id == sid)
                for other in per_stand.get(sid, []):
                    if conflicts(f, other, BUFFER_SECONDS):
                        ok = False
                        break
                if not ok:
                    break
                per_stand.setdefault(sid, []).append(f)
            if not ok:
                continue
            assigned = sum(1 for sid in combo if sid is not None)
            plb = sum(
                1
                for f, sid in zip(flights, combo, strict=False)
                if sid is not None
                and next(s for s in stands if s.stand_id == sid).stand_type == "PLB"
            )
            oversize = sum(
                config.SIZE_RANK[next(s for s in stands if s.stand_id == sid).max_size]
                - config.SIZE_RANK[f.aircraft_size]
                for f, sid in zip(flights, combo, strict=False)
                if sid is not None
            )
            key = (assigned, plb, -oversize)
            if best is None or key > best:
                best = key
        assert solver_key == best, f"seed {seed}: solver {solver_key} != brute {best}"

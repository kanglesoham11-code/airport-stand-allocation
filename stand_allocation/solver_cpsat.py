"""Primary allocator: exact CP-SAT model (section 9.4A).

One Boolean variable per compatible flight/stand pair, one optional interval
per stand, one at-most-one constraint per flight and one no-overlap constraint
per stand. The objective encodes the ordered preferences: assigned count first,
then PLB count, then best fit (smallest oversize).
"""

from __future__ import annotations

from time import monotonic

from ortools.sat.python import cp_model

from stand_allocation import config
from stand_allocation.allocator import fits
from stand_allocation.models import Flight, SolverOutcome, Stand
from stand_allocation.timeutil import seconds_from_window_start


def _worker_parameter_name(solver: cp_model.CpSolver) -> str:
    """OR-Tools renamed num_search_workers to num_workers in version 9.10."""
    if hasattr(solver.parameters, "num_workers"):
        return "num_workers"
    return "num_search_workers"


def solve_cpsat(
    flights: list[Flight],
    stands: list[Stand],
    buffer_seconds: int,
    time_limit_seconds: float,
    seed: int,
) -> SolverOutcome:
    """Solve the allocation model and return the outcome."""
    if not flights:
        return SolverOutcome(status="NOT_RUN", assignment={}, solve_seconds=0.0)

    flights = sorted(flights, key=lambda f: (f.arrival, f.flight_id))
    stands = sorted(stands, key=lambda s: s.stand_id)
    compat = {f.flight_id: [s for s in stands if fits(f, s)] for f in flights}
    if not any(compat.values()):
        return SolverOutcome(status="NOT_RUN", assignment={}, solve_seconds=0.0)

    started = monotonic()
    model = cp_model.CpModel()
    presence: dict[tuple[str, str], cp_model.IntVar] = {}
    stand_intervals: dict[str, list] = {s.stand_id: [] for s in stands}

    for flight in flights:
        start_s = seconds_from_window_start(flight.arrival, config.WINDOW_START)
        end_s = (
            seconds_from_window_start(flight.departure, config.WINDOW_START)
            + buffer_seconds
        )
        for stand in compat[flight.flight_id]:
            var = model.NewBoolVar(f"x_{flight.flight_id}_{stand.stand_id}")
            presence[(flight.flight_id, stand.stand_id)] = var
            stand_intervals[stand.stand_id].append(
                model.NewOptionalIntervalVar(
                    start_s,
                    end_s - start_s,
                    end_s,
                    var,
                    f"i_{flight.flight_id}_{stand.stand_id}",
                )
            )

    # C1: at most one stand per flight.
    for flight in flights:
        options = [presence[(flight.flight_id, s.stand_id)] for s in compat[flight.flight_id]]
        if options:
            model.AddAtMostOne(options)

    # C2: no overlapping intervals on each stand (enforces the buffer).
    for stand in stands:
        if stand_intervals[stand.stand_id]:
            model.AddNoOverlap(stand_intervals[stand.stand_id])

    # Lexicographic objective: assigned count, then PLB count, then oversize.
    f_count = len(flights)
    gap = max(config.SIZE_RANK.values()) - min(config.SIZE_RANK.values())  # 2
    plb_weight = f_count * gap + 1
    assign_weight = f_count * plb_weight + f_count * gap + 1
    terms = []
    for flight in flights:
        for stand in compat[flight.flight_id]:
            weight = (
                assign_weight
                + (plb_weight if stand.stand_type == "PLB" else 0)
                - (config.SIZE_RANK[stand.max_size] - config.SIZE_RANK[flight.aircraft_size])
            )
            terms.append(weight * presence[(flight.flight_id, stand.stand_id)])
    if terms:
        model.Maximize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    setattr(solver.parameters, _worker_parameter_name(solver), config.SOLVER_NUM_WORKERS)
    solver.parameters.random_seed = seed

    status = solver.StatusName(solver.Solve(model))
    elapsed = monotonic() - started

    if status not in ("OPTIMAL", "FEASIBLE"):
        return SolverOutcome(status=status, assignment=None, solve_seconds=elapsed)

    assignment: dict[str, str | None] = {}
    for flight in flights:
        chosen: str | None = None
        for stand in compat[flight.flight_id]:
            if solver.Value(presence[(flight.flight_id, stand.stand_id)]) == 1:
                chosen = stand.stand_id
                break
        assignment[flight.flight_id] = chosen

    return SolverOutcome(status=status, assignment=assignment, solve_seconds=elapsed)

"""Startup pipeline: load, check, allocate, metric, save (section 4.4).

The service builds one run at startup and the API only ever reads that run.
Nothing is recomputed per request.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stand_allocation import config
from stand_allocation.allocator import build_allocations, greedy_loop, post_process
from stand_allocation.db import connect
from stand_allocation.loader import load_stands, read_flight_rows
from stand_allocation.metrics import compute_comparison_metrics, compute_primary_metrics
from stand_allocation.models import (
    Allocation,
    SavedRun,
    Stand,
)
from stand_allocation.repository import (
    FutureSchemaError,
    migrate,
    save_run,
)
from stand_allocation.validation import validate_rows

logger = logging.getLogger("stand_allocation")

_solver_cpsat: Any = None
if config.ALLOCATOR == "cpsat":
    try:
        from stand_allocation import solver_cpsat as _solver_cpsat
    except ImportError as exc:
        logger.error("CP-SAT solver unavailable: %s", exc)
        print(
            "stand-allocation: the ortools package is required for "
            f"ALLOCATOR=cpsat ({exc}). Set ALLOCATOR=greedy to run without the solver.",
            file=sys.stderr,
        )
        sys.exit(1)


def compute_input_hashes(paths: list[Path]) -> dict[str, str]:
    """SHA-256 of each input file, keyed by file name (section 23.12)."""
    digests: dict[str, str] = {}
    for path in paths:
        data = path.read_bytes()
        digests[path.name] = hashlib.sha256(data).hexdigest()
    return digests


def _oversize_total(
    allocations: list[Allocation], stands_by_max_size: dict[str, str]
) -> int:
    return sum(
        1
        for a in allocations
        if a.status == "ASSIGNED"
        and a.stand_id is not None
        and config.SIZE_RANK[stands_by_max_size[a.stand_id]]
        > config.SIZE_RANK[a.aircraft_size]
    )


def _candidate_key(
    allocations: list[Allocation], stands_by_max_size: dict[str, str]
) -> tuple[int, int, int]:
    """Primary choice key: (assigned, PLB, negative oversize). Greater wins."""
    assigned = sum(1 for a in allocations if a.status == "ASSIGNED")
    plb = sum(
        1
        for a in allocations
        if a.status == "ASSIGNED" and a.stand_type == "PLB"
    )
    return (assigned, plb, -_oversize_total(allocations, stands_by_max_size))


def build_run() -> SavedRun:
    """Run the full startup pipeline and return the saved run."""
    buffer_seconds = config.BUFFER_MINUTES * config.SECONDS_PER_MINUTE

    # 1-6: load stands and flights, validate, hash inputs (section 4.4).
    stands_raw = load_stands(config.STANDS_CSV)
    stands = [
        Stand(r.fields[0], r.fields[1], r.fields[2]) for r in stands_raw
    ]
    flights_raw = read_flight_rows(config.FLIGHTS_CSV)
    flights, data_issues = validate_rows(flights_raw)
    input_hashes = compute_input_hashes([config.STANDS_CSV, config.FLIGHTS_CSV])

    # 7-8: allocate. Both candidates run; the primary is chosen by key.
    greedy_assignments = greedy_loop(flights, stands, buffer_seconds)
    greedy_post = post_process(greedy_assignments, flights, stands, buffer_seconds)
    greedy_allocations = list(
        build_allocations(greedy_post, flights, stands, buffer_seconds)
    )

    solver_status = "NOT_RUN"
    solver_seconds = 0.0
    solver_allocations: list[Allocation] | None = None

    if config.ALLOCATOR == "cpsat" and _solver_cpsat is not None:
        outcome = _solver_cpsat.solve_cpsat(
            flights,
            stands,
            buffer_seconds,
            config.SOLVER_TIME_LIMIT_SECONDS,
            config.RANDOM_SEED,
        )
        solver_status = outcome.status
        solver_seconds = outcome.solve_seconds
        if outcome.assignment is not None:
            solver_post = post_process(
                outcome.assignment, flights, stands, buffer_seconds
            )
            solver_allocations = list(
                build_allocations(solver_post, flights, stands, buffer_seconds)
            )

    stands_by_max_size = {s.stand_id: s.max_size for s in stands}

    if config.ALLOCATOR == "greedy":
        primary_allocations = greedy_allocations
        primary_method = "greedy"
    elif solver_allocations is None:
        primary_allocations = greedy_allocations
        primary_method = "FALLBACK_GREEDY"
    else:
        solver_key = _candidate_key(solver_allocations, stands_by_max_size)
        greedy_key = _candidate_key(greedy_allocations, stands_by_max_size)
        if solver_key >= greedy_key:
            primary_allocations = solver_allocations
            primary_method = "cpsat"
        else:
            primary_allocations = greedy_allocations
            primary_method = "FALLBACK_GREEDY"

    # 9: metrics.
    primary_metrics = compute_primary_metrics(
        primary_allocations, stands, buffer_seconds
    )
    comparison_metrics = compute_comparison_metrics(
        primary_allocations, greedy_allocations
    )
    metrics = list(primary_metrics) + list(comparison_metrics)

    # 10-11: save the run in one transaction.
    conn = connect(config.DB_PATH)
    try:
        migrate(conn)
        run_id = save_run(
            conn=conn,
            run_id=None,
            buffer_minutes=config.BUFFER_MINUTES,
            allocator=config.ALLOCATOR,
            primary_method=primary_method,
            solver_status=solver_status,
            solve_seconds=solver_seconds,
            input_hashes=input_hashes,
            stands=stands,
            primary_allocations=primary_allocations,
            baseline_allocations=greedy_allocations,
            data_issues=list(data_issues),
            metrics=metrics,
        )
    finally:
        conn.close()

    # 12: one summary line (section 4.4 step 8).
    assigned = sum(1 for a in primary_allocations if a.status == "ASSIGNED")
    plb = sum(
        1
        for a in primary_allocations
        if a.status == "ASSIGNED" and a.stand_type == "PLB"
    )
    logger.info(
        "run %s complete: %d/%d flights assigned, %d PLB, allocator=%s, "
        "primary_method=%s, solver_status=%s, issues=%d",
        run_id,
        assigned,
        len(flights),
        plb,
        config.ALLOCATOR,
        primary_method,
        solver_status,
        len(data_issues),
    )

    now = datetime.now(timezone.utc)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"
    return SavedRun(
        run_id=run_id,
        status="COMPLETE",
        created_at=created_at,
        buffer_minutes=config.BUFFER_MINUTES,
        allocator=config.ALLOCATOR,
        primary_method=primary_method,
        solver_status=solver_status,
        solve_seconds=solver_seconds,
        input_hashes=input_hashes,
        stands=tuple(stands),
        allocations=tuple(primary_allocations),
        baseline_allocations=tuple(greedy_allocations),
        data_issues=tuple(data_issues),
        metrics=tuple(metrics),
    )


def get_latest_run() -> SavedRun | None:
    """Read the latest complete run from the database (section 23.46)."""
    conn = connect(config.DB_PATH)
    try:
        from stand_allocation.repository import latest_run

        return latest_run(conn)
    except FutureSchemaError:
        logger.warning("Database schema version is newer than supported", exc_info=True)
        return None
    except Exception:
        logger.warning("Failed to read latest run from database", exc_info=True)
        return None
    finally:
        conn.close()

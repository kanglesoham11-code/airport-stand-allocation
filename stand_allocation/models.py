"""Core domain models.

All result objects are frozen dataclasses: they are created once and never
edited in place (section 4.6, "Frozen dataclasses").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Flight:
    """A valid flight ready for allocation."""

    flight_id: str
    aircraft_size: str  # one of S, M, L
    arrival: datetime  # timezone-aware UTC
    departure: datetime  # timezone-aware UTC


@dataclass(frozen=True)
class Stand:
    """An airport stand."""

    stand_id: str
    stand_type: str  # "PLB" or "REMOTE"
    max_size: str  # one of S, M, L


@dataclass(frozen=True)
class Allocation:
    """The outcome for one flight under one allocator method."""

    flight_id: str
    aircraft_size: str
    arrival: datetime
    departure: datetime
    status: str  # "ASSIGNED" or "UNASSIGNED"
    stand_id: str | None
    stand_type: str | None
    note: str | None
    reason_code: str | None
    reason: str | None
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataIssue:
    """One checked row problem, as shown by the /data-issues endpoint."""

    row_number: int
    flight_id: str
    field: str  # row, flight_id, aircraft_size, arrival_time, departure_time
    issue_code: str
    action: str  # "DROPPED" or "FIXED"
    original_value: str
    new_value: str | None
    explanation: str


@dataclass(frozen=True)
class Metric:
    """One planning metric record."""

    id: str
    name: str
    value: float | None
    unit: str
    window: str
    flights_covered: int
    definition: str
    why_it_matters: str


@dataclass(frozen=True)
class Candidate:
    """One complete allocation candidate (baseline or primary)."""

    allocations: tuple[Allocation, ...]
    assigned_count: int
    plb_count: int
    oversize_total: int
    method: str
    solver_status: str
    solve_seconds: float

    @property
    def key(self) -> tuple[int, int, int]:
        """Primary choice key: (assigned, PLB, negative oversize). Greater wins."""
        return (self.assigned_count, self.plb_count, -self.oversize_total)


@dataclass(frozen=True)
class SolverOutcome:
    """The result returned by the CP-SAT solver."""

    status: str  # "OPTIMAL", "FEASIBLE", "UNKNOWN", "INFEASIBLE", "MODEL_INVALID", "NOT_RUN"
    assignment: dict[str, str | None] | None  # flight_id -> stand_id, or None
    solve_seconds: float


@dataclass(frozen=True)
class SavedRun:
    """Everything persisted for one run."""

    run_id: str
    status: str
    created_at: str
    buffer_minutes: int
    allocator: str
    primary_method: str
    solver_status: str
    solve_seconds: float
    input_hashes: dict[str, str]
    stands: tuple[Stand, ...]
    allocations: tuple[Allocation, ...]  # primary allocations only
    baseline_allocations: tuple[Allocation, ...]
    data_issues: tuple[DataIssue, ...]
    metrics: tuple[Metric, ...]

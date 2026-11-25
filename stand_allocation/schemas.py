"""API response shapes (section 10.2 and 10.3).

All responses are JSON. pydantic v2 models are used for serialization and for
FastAPI's automatic /docs schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

AircraftSize = Literal["S", "M", "L"]
StandType = Literal["PLB", "REMOTE"]
AllocationStatus = Literal["ASSIGNED", "UNASSIGNED"]
DataIssueAction = Literal["DROPPED", "FIXED"]


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    flight_id: str
    aircraft_size: AircraftSize
    arrival_time: str
    departure_time: str
    status: AllocationStatus
    stand_id: str | None = None
    stand_type: StandType | None = None
    note: str | None = None
    reason_code: str | None = None
    reason: str | None = None


class PlanningWindowOut(BaseModel):
    start: str
    end: str


class AllocationsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    planning_window: PlanningWindowOut
    run_id: str
    allocator: str
    primary_method: str
    solver_status: str
    total: int
    limit: int
    offset: int
    allocations: list[AllocationOut]


class StandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stand_id: str
    stand_type: StandType
    max_size: AircraftSize


class StandDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stand_id: str
    stand_type: StandType
    max_size: AircraftSize
    flight_count: int
    flights: list[AllocationOut]


class ReadyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    run_id: str | None = None
    stands: int = 0
    valid_flights: int = 0
    data_issues: int = 0
    loaded_at: str | None = None
    allocator: str | None = None
    primary_method: str | None = None
    solver_status: str | None = None


class HealthOut(BaseModel):
    status: str = "ok"


class MetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    value: float | None = None
    unit: str
    window: str
    flights_covered: int
    definition: str
    why_it_matters: str


class MetricsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    planning_window: PlanningWindowOut
    metrics: list[MetricOut]


class DataIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    flight_id: str
    field: str
    issue_code: str
    action: DataIssueAction
    original_value: str
    new_value: str | None = None
    explanation: str


class DataIssuesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    count: int
    dropped: int
    fixed: int
    issues: list[DataIssueOut]


class OpsStatsOut(BaseModel):
    uptime_seconds: float
    run_id: str | None = None
    requests_total: dict[str, int]
    rate_limited_total: int
    auth_failed_total: int
    latency_p95_ms: float


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorOut(BaseModel):
    error: ErrorBody

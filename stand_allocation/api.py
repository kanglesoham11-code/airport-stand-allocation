"""HTTP API (sections 10, 10A and 23.42-23.46).

The API only reads the latest complete run. Every data endpoint needs an API
key. Errors all use one JSON shape.
"""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from stand_allocation import config, models, schemas, service
from stand_allocation.logging_setup import setup_logging
from stand_allocation.middleware import RequestPipelineMiddleware
from stand_allocation.ops import OpsCounters
from stand_allocation.ratelimit import TokenBucketStore

setup_logging()

app = FastAPI(title="Aleph Airport Stand Allocation", docs_url="/docs")

RUN_ID: str | None = None
_CACHED_RUN: service.SavedRun | None = None  # Set at startup; read per request.
COUNTERS = OpsCounters()
GENERAL_STORE = TokenBucketStore()
FAILURE_STORE = TokenBucketStore()


class ApiError(StarletteHTTPException):
    """An error with a stable code and message, rendered in the standard shape."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message},
            headers=headers,
        )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "request_id": _request_id(request)}},
        status_code=status_code,
        headers=headers,
    )


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return _error(
            request,
            exc.status_code,
            exc.detail["code"],
            exc.detail["message"],
            exc.headers,
        )
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        413: "PAYLOAD_TOO_LARGE",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        503: "NOT_READY",
    }
    return _error(
        request,
        exc.status_code,
        code_map.get(exc.status_code, "ERROR"),
        str(exc.detail),
        exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error(request, 422, "VALIDATION_ERROR", "Invalid request parameters.")


def _get_run() -> service.SavedRun:
    """Return the cached run from memory, or raise 503."""
    if _CACHED_RUN is None:
        raise ApiError(503, "NOT_READY", "No complete run is available.")
    return _CACHED_RUN


def _window() -> schemas.PlanningWindowOut:
    return schemas.PlanningWindowOut(
        start=config.WINDOW_START.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end=config.WINDOW_END.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _paginate(items, limit: int, offset: int):
    total = len(items)
    page = items[offset: offset + limit]
    return total, page


@app.get("/health", response_model=schemas.HealthOut)
def health() -> schemas.HealthOut:
    return schemas.HealthOut()


@app.get("/ready", response_model=schemas.ReadyOut)
def ready(request: Request) -> schemas.ReadyOut:
    run = _CACHED_RUN
    if run is None:
        return _error(request, 503, "NOT_READY", "No complete run is available.")
    return schemas.ReadyOut(
        status="ready",
        run_id=run.run_id,
        stands=len(run.stands),
        valid_flights=len(run.allocations),
        data_issues=len(run.data_issues),
        loaded_at=run.created_at,
        allocator=run.allocator,
        primary_method=run.primary_method,
        solver_status=run.solver_status,
    )


@app.get("/ops/stats", response_model=schemas.OpsStatsOut)
def ops_stats(request: Request) -> schemas.OpsStatsOut:
    run = _CACHED_RUN
    return schemas.OpsStatsOut(**COUNTERS.snapshot(run.run_id if run else None))


def _allocation_out(a: models.Allocation) -> schemas.AllocationOut:
    return schemas.AllocationOut(
        flight_id=a.flight_id,
        aircraft_size=cast(schemas.AircraftSize, a.aircraft_size),
        arrival_time=a.arrival.strftime("%Y-%m-%dT%H:%M:%SZ"),
        departure_time=a.departure.strftime("%Y-%m-%dT%H:%M:%SZ"),
        status=cast(schemas.AllocationStatus, a.status),
        stand_id=a.stand_id,
        stand_type=cast(schemas.StandType | None, a.stand_type),
        note=a.note,
        reason_code=a.reason_code,
        reason=a.reason,
    )


@app.get("/allocations", response_model=schemas.AllocationsOut)
def allocations(
    request: Request,
    status: str | None = Query(default=None),
    limit: str | None = Query(default=None),
    offset: str | None = Query(default=None),
) -> schemas.AllocationsOut:
    run = _get_run()
    # Unknown query parameters.
    allowed = {"status", "limit", "offset"}
    extra = set(request.query_params.keys()) - allowed
    if extra:
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    if status is not None and status not in ("ASSIGNED", "UNASSIGNED"):
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    try:
        page_limit = config.DEFAULT_PAGE_LIMIT if limit is None else int(limit)
        page_offset = 0 if offset is None else int(offset)
    except (TypeError, ValueError):
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    if not (1 <= page_limit <= config.MAX_PAGE_LIMIT):
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    if page_offset < 0:
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    items = [a for a in run.allocations if status is None or a.status == status]
    total, page = _paginate(items, page_limit, page_offset)
    return schemas.AllocationsOut(
        planning_window=_window(),
        run_id=run.run_id,
        allocator=run.allocator,
        primary_method=run.primary_method,
        solver_status=run.solver_status,
        total=total,
        limit=page_limit,
        offset=page_offset,
        allocations=[_allocation_out(a) for a in page],
    )


@app.get("/stands", response_model=list[schemas.StandOut])
def stands(request: Request) -> list[schemas.StandOut]:
    run = _get_run()
    return [
        schemas.StandOut(
            stand_id=s.stand_id,
            stand_type=cast(schemas.StandType, s.stand_type),
            max_size=cast(schemas.AircraftSize, s.max_size),
        )
        for s in run.stands
    ]


@app.get("/stands/{stand_id}", response_model=schemas.StandDetailOut)
def stand_detail(request: Request, stand_id: str) -> schemas.StandDetailOut:
    run = _get_run()
    import re as _re

    if not _re.fullmatch(r"[A-Z0-9]{1,8}", stand_id or ""):
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    stand = next((s for s in run.stands if s.stand_id == stand_id), None)
    if stand is None:
        raise ApiError(404, "STAND_NOT_FOUND", f"Stand '{stand_id}' not found")
    flights = [a for a in run.allocations if a.stand_id == stand_id]
    return schemas.StandDetailOut(
        stand_id=stand.stand_id,
        stand_type=cast(schemas.StandType, stand.stand_type),
        max_size=cast(schemas.AircraftSize, stand.max_size),
        flight_count=len(flights),
        flights=[_allocation_out(a) for a in flights],
    )


@app.get("/data-issues", response_model=schemas.DataIssuesOut)
def data_issues(
    request: Request,
    limit: str | None = Query(default=None),
    offset: str | None = Query(default=None),
) -> schemas.DataIssuesOut:
    run = _get_run()
    allowed = {"limit", "offset"}
    extra = set(request.query_params.keys()) - allowed
    if extra:
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    try:
        page_limit = config.DEFAULT_PAGE_LIMIT if limit is None else int(limit)
        page_offset = 0 if offset is None else int(offset)
    except (TypeError, ValueError):
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    if not (1 <= page_limit <= config.MAX_PAGE_LIMIT):
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    if page_offset < 0:
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request parameters.") from None
    issues = list(run.data_issues)
    dropped = sum(1 for i in issues if i.action == "DROPPED")
    fixed = sum(1 for i in issues if i.action == "FIXED")
    total, page = _paginate(issues, page_limit, page_offset)
    return schemas.DataIssuesOut(
        count=len(issues),
        dropped=dropped,
        fixed=fixed,
        issues=[
            schemas.DataIssueOut(
                row_number=i.row_number,
                flight_id=i.flight_id,
                field=i.field,
                issue_code=i.issue_code,
                action=cast(schemas.DataIssueAction, i.action),
                original_value=i.original_value,
                new_value=i.new_value,
                explanation=i.explanation,
            )
            for i in page
        ],
    )


@app.get("/metrics", response_model=schemas.MetricsOut)
def metrics(request: Request) -> schemas.MetricsOut:
    run = _get_run()
    return schemas.MetricsOut(
        planning_window=_window(),
        metrics=[
            schemas.MetricOut(
                id=m.id,
                name=m.name,
                value=m.value,
                unit=m.unit,
                window=m.window,
                flights_covered=m.flights_covered,
                definition=m.definition,
                why_it_matters=m.why_it_matters,
            )
            for m in run.metrics
        ],
    )


# Catch-all: unknown paths return 404 in the standard shape. Registered last.
@app.api_route(
    "/{path_name:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def _catch_all(path_name: str, request: Request) -> None:
    raise ApiError(404, "NOT_FOUND", "Route not found.")


def create_app() -> FastAPI:
    """Build the run at startup, cache in memory, and wire middleware (section 4.4)."""
    global RUN_ID, _CACHED_RUN
    run = service.build_run()
    RUN_ID = run.run_id
    _CACHED_RUN = run

    app.add_middleware(
        RequestPipelineMiddleware,
        general_store=GENERAL_STORE,
        failure_store=FAILURE_STORE,
        counters=COUNTERS,
        run_id=RUN_ID,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.ALLOWED_ORIGINS if config.ALLOWED_ORIGINS else [],
        allow_methods=["GET"],
        allow_headers=["X-API-Key", "X-Request-ID", "If-None-Match"],
    )

    return app


app = create_app()

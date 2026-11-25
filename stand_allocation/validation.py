"""Row-level validation of flight data (sections 8.2, 8.2A and 23.5-23.9).

Each data row is checked in order. A row with any DROPPED issue is dropped;
its FIXED issues are still logged. A row with no DROPPED issue is kept and its
FIXED changes are applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from stand_allocation import config
from stand_allocation.models import DataIssue, Flight
from stand_allocation.timeutil import TimestampError, format_utc, parse_utc

# Field order used to sort issues within a row (section 8.2A, "Issue order").
FIELD_ORDER: Final[list[str]] = [
    "row",
    "flight_id",
    "aircraft_size",
    "arrival_time",
    "departure_time",
]
_FIELD_INDEX = {name: idx for idx, name in enumerate(FIELD_ORDER)}

# Issue codes that mark a row for dropping.
DROPPED_CODES: Final[frozenset[str]] = frozenset(
    {
        "WRONG_FIELD_COUNT",
        "EMPTY_FLIGHT_ID",
        "DUPLICATE_FLIGHT_ID",
        "UNKNOWN_SIZE",
        "MISSING_VALUE",
        "BAD_TIMESTAMP",
        "NAIVE_TIMESTAMP",
        "DEPARTURE_BEFORE_ARRIVAL",
        "GROUND_TOO_SHORT",
        "GROUND_TOO_LONG",
        "ARRIVAL_OUTSIDE_WINDOW",
    }
)


@dataclass
class _Context:
    row_number: int
    flight_id: str = ""
    issues: list[DataIssue] | None = None

    def __post_init__(self) -> None:
        if self.issues is None:
            self.issues = []


def _issue(
    ctx: _Context,
    field: str,
    code: str,
    action: str,
    original_value: str,
    new_value: str | None,
    explanation: str,
) -> None:
    ctx.issues.append(
        DataIssue(
            row_number=ctx.row_number,
            flight_id=ctx.flight_id,
            field=field,
            issue_code=code,
            action=action,
            original_value=original_value,
            new_value=new_value,
            explanation=explanation,
        )
    )


def _sort_key(issue: DataIssue) -> tuple[int, int, str]:
    return (
        issue.row_number,
        _FIELD_INDEX.get(issue.field, len(FIELD_ORDER)),
        issue.issue_code,
    )


def validate_rows(raw_rows: list) -> tuple[list[Flight], list[DataIssue]]:
    """Validate every raw row and return (valid flights, data issues)."""
    flights: list[Flight] = []
    issues: list[DataIssue] = []
    kept_ids: set[str] = set()

    for raw in raw_rows:
        ctx = _Context(row_number=raw.line_number, flight_id="", issues=[])
        fields = raw.fields

        # Step 1: field count.
        if len(fields) != 4:
            _issue(
                ctx,
                "row",
                "WRONG_FIELD_COUNT",
                "DROPPED",
                f"{len(fields)} fields",
                None,
                f"the row has {len(fields)} fields, expected 4",
            )
            issues.extend(ctx.issues)
            continue

        flight_id_raw, size_raw, arrival_raw, departure_raw = fields
        flight_id = flight_id_raw.strip()
        ctx.flight_id = flight_id

        # Step 2: empty flight id.
        if flight_id == "":
            _issue(
                ctx,
                "flight_id",
                "EMPTY_FLIGHT_ID",
                "DROPPED",
                flight_id_raw,
                None,
                "flight_id is empty after trimming spaces",
            )
            issues.extend(ctx.issues)
            continue

        # Step 3: duplicate among kept rows.
        if flight_id in kept_ids:
            _issue(
                ctx,
                "flight_id",
                "DUPLICATE_FLIGHT_ID",
                "DROPPED",
                flight_id,
                None,
                f"flight_id {flight_id} was already kept by an earlier row; "
                f"the first occurrence is kept",
            )
            issues.extend(ctx.issues)
            continue

        # Working copies of values that may be fixed.
        size = size_raw.strip()
        arrival_text = arrival_raw.strip()
        departure_text = departure_raw.strip()
        arrival: datetime | None = None
        departure: datetime | None = None
        stopped = False  # true when a time check failed and later checks are skipped

        # Step 4: aircraft size.
        candidate = size.upper()
        if candidate not in config.VALID_SIZES:
            _issue(
                ctx,
                "aircraft_size",
                "UNKNOWN_SIZE",
                "DROPPED",
                size,
                None,
                f'aircraft size "{size}" is not S, M or L',
            )
            stopped = True
        elif candidate != size:
            _issue(
                ctx,
                "aircraft_size",
                "SIZE_FORMAT",
                "FIXED",
                size,
                candidate,
                f'aircraft size was "{size}"; changed to "{candidate}"',
            )
            size = candidate

        if not stopped:
            # Step 5-8: arrival time.
            try:
                arrival = _parse_time_field(ctx, "arrival_time", arrival_text)
            except TimestampError as exc:
                _issue(
                    ctx,
                    "arrival_time",
                    exc.code,
                    "DROPPED",
                    arrival_text,
                    None,
                    exc.message,
                )
                stopped = True

        if not stopped:
            # Steps 9-12: departure time.
            try:
                departure = _parse_time_field(ctx, "departure_time", departure_text)
            except TimestampError as exc:
                _issue(
                    ctx,
                    "departure_time",
                    exc.code,
                    "DROPPED",
                    departure_text,
                    None,
                    exc.message,
                )
                stopped = True

        if not stopped:
            # Step 13: departure after arrival. On failure, skip steps 14-15.
            assert arrival is not None and departure is not None
            if not departure > arrival:
                _issue(
                    ctx,
                    "departure_time",
                    "DEPARTURE_BEFORE_ARRIVAL",
                    "DROPPED",
                    departure_text,
                    None,
                    f"Departure ({format_utc(departure)}) is before arrival "
                    f"({format_utc(arrival)}).",
                )
                stopped = True

        if not stopped:
            # Steps 14-15: ground time.
            assert arrival is not None and departure is not None
            ground_seconds = int((departure - arrival).total_seconds())
            min_seconds = config.MIN_GROUND_MINUTES * config.SECONDS_PER_MINUTE
            max_seconds = (
                config.MAX_GROUND_HOURS
                * config.MINUTES_PER_HOUR
                * config.SECONDS_PER_MINUTE
            )
            if ground_seconds < min_seconds:
                _issue(
                    ctx,
                    "departure_time",
                    "GROUND_TOO_SHORT",
                    "DROPPED",
                    departure_text,
                    None,
                    f"Ground time of {ground_seconds // config.SECONDS_PER_MINUTE} "
                    f"minutes is below the {config.MIN_GROUND_MINUTES}-minute minimum.",
                )
                stopped = True
            elif ground_seconds > max_seconds:
                _issue(
                    ctx,
                    "departure_time",
                    "GROUND_TOO_LONG",
                    "DROPPED",
                    departure_text,
                    None,
                    f"Ground time of {ground_seconds // config.SECONDS_PER_MINUTE} "
                    f"minutes is above the {config.MAX_GROUND_HOURS}-hour maximum.",
                )
                stopped = True

        if not stopped:
            # Step 16: planning window (still runs when step 13 failed).
            assert arrival is not None
            if not (config.WINDOW_START <= arrival < config.WINDOW_END):
                _issue(
                    ctx,
                    "arrival_time",
                    "ARRIVAL_OUTSIDE_WINDOW",
                    "DROPPED",
                    arrival_text,
                    None,
                    f"Arrival {format_utc(arrival)} UTC is outside "
                    f"the planning window.",
                )
                stopped = True

        issues.extend(ctx.issues)

        # Decision rule: drop if any DROPPED issue; otherwise keep and apply FIXED.
        if any(issue.action == "DROPPED" for issue in ctx.issues):
            continue

        kept_ids.add(flight_id)
        flights.append(
            Flight(
                flight_id=flight_id,
                aircraft_size=size,
                arrival=arrival,  # type: ignore[arg-type]
                departure=departure,  # type: ignore[arg-type]
            )
        )

    issues.sort(key=_sort_key)
    return flights, issues


def _parse_time_field(ctx: _Context, field: str, text: str) -> datetime:
    """Parse one timestamp field, logging OFFSET_TIMESTAMP as FIXED when needed."""
    ends_with_z = text.endswith("Z") or text.endswith("z")
    value = parse_utc(text)  # raises TimestampError on missing/bad/naive/fractional
    if not ends_with_z:
        _issue(
            ctx,
            field,
            "OFFSET_TIMESTAMP",
            "FIXED",
            text,
            value.strftime("%Y-%m-%dT%H:%M:%SZ"),
            f"{field} had an offset; converted to UTC",
        )
    return value

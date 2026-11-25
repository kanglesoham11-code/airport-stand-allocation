"""Planning metrics (section 11 and 23.25-23.30).

M1 to M6 are computed from the primary result. M7 and M8 compare the primary
with the baseline. Percentages use Decimal arithmetic with ROUND_HALF_UP and
are rounded only in the output, never inside a calculation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from stand_allocation import config
from stand_allocation.models import Allocation, Metric

WINDOW_TEXT = "06:00-12:00 UTC (all valid flights)"


def percent(numerator: int, denominator: int) -> float | None:
    """Percentage to one decimal place, ROUND_HALF_UP. None if denominator is 0."""
    if denominator == 0:
        return None
    value = (
        Decimal(numerator)
        * Decimal(config.PERCENT_SCALE)
        / Decimal(denominator)
    ).quantize(Decimal(10) ** -config.PERCENT_DECIMALS, rounding=ROUND_HALF_UP)
    return float(value)


def peak_demand(
    assigned: list[Allocation], buffer_seconds: int
) -> tuple[int, datetime | None]:
    """Sweep line for M3: max concurrent occupied stands and the first time reached.

    Each assigned flight creates a start (+1) at arrival and an end (-1) at
    departure + buffer. At equal times the end is handled before the start,
    matching the half-open interval [arrival, departure + buffer).
    """
    events: list[tuple[datetime, int]] = []
    for flight in assigned:
        events.append((flight.arrival, 1))
        events.append((flight.departure + timedelta(seconds=buffer_seconds), -1))
    events.sort(key=lambda event: (event[0], event[1]))

    count = 0
    best = 0
    best_time: datetime | None = None
    for when, delta in events:
        count += delta
        if count > best:
            best = count
            best_time = when
    return best, best_time


def utilisation(
    assigned: list[Allocation], stand_count: int
) -> tuple[float, int]:
    """M4: clipped occupied seconds divided by stand_count × window seconds."""
    window_start_s = 0
    window_end_s = config.WINDOW_LENGTH_SECONDS
    occupied_seconds = 0
    for flight in assigned:
        arr_s = int((flight.arrival - config.WINDOW_START).total_seconds())
        dep_s = int((flight.departure - config.WINDOW_START).total_seconds())
        clipped = max(0, min(dep_s, window_end_s) - max(arr_s, window_start_s))
        occupied_seconds += clipped
    denominator = stand_count * config.WINDOW_LENGTH_SECONDS
    p = percent(occupied_seconds, denominator)
    return (p if p is not None else 0.0, occupied_seconds)


def tight_turns(per_stand: dict[str, list[Allocation]]) -> int:
    """M5: consecutive pairs on a stand whose gap is below TIGHT_TURN_MINUTES."""
    limit = config.TIGHT_TURN_MINUTES * config.SECONDS_PER_MINUTE
    count = 0
    for flights in per_stand.values():
        ordered = sorted(flights, key=lambda f: (f.arrival, f.flight_id))
        for prev, nxt in zip(ordered, ordered[1:], strict=False):
            gap = int((nxt.arrival - prev.departure).total_seconds())
            if gap < limit:
                count += 1
    return count


def oversized_count(allocations: list[Allocation], stands_by_id: dict[str, str]) -> int:
    """M6: assigned flights whose stand max_size rank exceeds their aircraft size rank."""
    count = 0
    for flight in allocations:
        if flight.status != "ASSIGNED" or flight.stand_id is None:
            continue
        stand_max_rank = config.SIZE_RANK[stands_by_id[flight.stand_id]]
        if stand_max_rank > config.SIZE_RANK[flight.aircraft_size]:
            count += 1
    return count


def per_stand(allocations: list[Allocation]) -> dict[str, list[Allocation]]:
    """Group assigned flights by stand id."""
    grouped: dict[str, list[Allocation]] = {}
    for flight in allocations:
        if flight.status == "ASSIGNED" and flight.stand_id is not None:
            grouped.setdefault(flight.stand_id, []).append(flight)
    return grouped


def compute_primary_metrics(
    allocations: list[Allocation], stands: list, buffer_seconds: int
) -> list[Metric]:
    """M1 to M6 from the primary result."""
    assigned = [a for a in allocations if a.status == "ASSIGNED"]
    unassigned = [a for a in allocations if a.status == "UNASSIGNED"]
    stand_count = len(stands)

    peak, peak_time = peak_demand(assigned, buffer_seconds)
    peak_window = WINDOW_TEXT
    if peak_time is not None:
        peak_window += f"; first reached at {peak_time.strftime('%H:%M')} UTC"

    util_pct, occupied_seconds = utilisation(assigned, stand_count)
    grouped = per_stand(allocations)
    stands_by_id = {s.stand_id: s.max_size for s in stands}

    return [
        Metric(
            id="M1",
            name="Assigned flights",
            value=float(len(assigned)),
            unit="flights",
            window=WINDOW_TEXT,
            flights_covered=len(allocations),
            definition="Number of valid flights given a stand.",
            why_it_matters="An unassigned flight gets no stand and no service.",
        ),
        Metric(
            id="M2",
            name="Unassigned flights",
            value=float(len(unassigned)),
            unit="flights",
            window=WINDOW_TEXT,
            flights_covered=len(allocations),
            definition="Number of valid flights that could not be placed.",
            why_it_matters="The planner's first concern: how many aircraft are left on the ground.",
        ),
        Metric(
            id="M3",
            name="Peak demand",
            value=float(peak),
            unit="stands",
            window=peak_window,
            flights_covered=len(assigned),
            definition="Highest number of stands occupied at the same instant, buffer included.",
            why_it_matters="Shows whether the airport has enough stands at its busiest moment.",
        ),
        Metric(
            id="M4",
            name="Stand utilisation",
            value=util_pct,
            unit="percent",
            window=WINDOW_TEXT,
            flights_covered=len(assigned),
            definition=(
                "Clipped occupied stand-seconds divided by stand_count x "
                "window seconds. "
                f"{occupied_seconds} of {stand_count * config.WINDOW_LENGTH_SECONDS} "
                "stand-seconds used."
            ),
            why_it_matters="How much of the available stand capacity is actually used.",
        ),
        Metric(
            id="M5",
            name="Tight turns",
            value=float(tight_turns(grouped)),
            unit="turns",
            window=WINDOW_TEXT,
            flights_covered=len(assigned),
            definition=(
                f"Consecutive flights on one stand with a gap below "
                f"{config.TIGHT_TURN_MINUTES} minutes."
            ),
            why_it_matters="Tight turns leave little margin for delays.",
        ),
        Metric(
            id="M6",
            name="Oversized placements",
            value=float(oversized_count(allocations, stands_by_id)),
            unit="placements",
            window=WINDOW_TEXT,
            flights_covered=len(assigned),
            definition=(
                "Assigned flights on a stand whose max_size rank is above the "
                "aircraft size rank."
            ),
            why_it_matters="Putting a small aircraft on a large stand wastes scarce capacity.",
        ),
    ]


def compute_comparison_metrics(
    primary: list[Allocation], baseline: list[Allocation]
) -> list[Metric]:
    """M7 and M8: primary minus baseline."""
    primary_assigned = sum(1 for a in primary if a.status == "ASSIGNED")
    baseline_assigned = sum(1 for a in baseline if a.status == "ASSIGNED")
    primary_plb = sum(
        1 for a in primary if a.status == "ASSIGNED" and a.stand_type == "PLB"
    )
    baseline_plb = sum(
        1 for a in baseline if a.status == "ASSIGNED" and a.stand_type == "PLB"
    )
    return [
        Metric(
            id="M7",
            name="PLB flights gained over baseline",
            value=float(primary_plb - baseline_plb),
            unit="flights",
            window=WINDOW_TEXT,
            flights_covered=len(primary),
            definition="Primary PLB count minus baseline PLB count.",
            why_it_matters=(
                "Shows how many more flights use PLB stands because of the exact method."
            ),
        ),
        Metric(
            id="M8",
            name="Assigned flights gained over baseline",
            value=float(primary_assigned - baseline_assigned),
            unit="flights",
            window=WINDOW_TEXT,
            flights_covered=len(primary),
            definition="Primary assigned count minus baseline assigned count.",
            why_it_matters="Shows how many more flights get a stand at all.",
        ),
    ]

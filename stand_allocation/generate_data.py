"""Deterministic data generator (sections 7.2 and 7.3).

Produces data/stands.csv and data/flights.csv. The output is fully determined
by RANDOM_SEED and the draw order, so every run generates identical files.
"""

from __future__ import annotations

import csv
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stand_allocation import config
from stand_allocation.timeutil import format_utc

logger = logging.getLogger("stand_allocation")

WINDOW_DATE = "2027-01-15"

# The nine bad rows of section 7.3. Each is a tuple of raw CSV field values.
# Row 7's flight_id is filled in from the first clean flight at generation time.
BAD_ROWS = [
    ("FR207", "m", f"{WINDOW_DATE}T07:15:00Z", f"{WINDOW_DATE}T08:40:00Z"),
    ("KT610", "S", f"{WINDOW_DATE}T11:40:00+05:30", f"{WINDOW_DATE}T07:05:00Z"),
    ("CZ411", "M", f"{WINDOW_DATE}T09:20:00Z", f"{WINDOW_DATE}T08:50:00Z"),
    ("DL902", "XL", f"{WINDOW_DATE}T07:40:00Z", f"{WINDOW_DATE}T09:10:00Z"),
    ("EV318", "S", f"{WINDOW_DATE}T10:05:00Z", ""),
    ("GO550", "M", f"{WINDOW_DATE} 09:00:00", f"{WINDOW_DATE}T10:30:00Z"),
    (None, "S", f"{WINDOW_DATE}T10:00:00Z", f"{WINDOW_DATE}T11:00:00Z"),  # duplicate
    ("BQ880", "S", f"{WINDOW_DATE}T09:00:00Z", f"{WINDOW_DATE}T09:04:00Z"),
    ("KT999", "L", f"{WINDOW_DATE}T12:10:00Z", f"{WINDOW_DATE}T13:50:00Z"),
]

STANDS = [
    ("C01", "PLB", "L"),
    ("C02", "PLB", "M"),
    ("C03", "PLB", "S"),
    ("C04", "PLB", "S"),
    ("R01", "REMOTE", "L"),
    ("R02", "REMOTE", "L"),
    ("R03", "REMOTE", "M"),
    ("R04", "REMOTE", "M"),
    ("R05", "REMOTE", "M"),
    ("R06", "REMOTE", "S"),
    ("R07", "REMOTE", "S"),
    ("R08", "REMOTE", "S"),
]


def _slot_time(slot: int) -> datetime:
    """06:00 UTC plus slot times 5 minutes, with zero seconds."""
    return datetime(2027, 1, 15, 6, 0, 0, tzinfo=timezone.utc) + timedelta(
        minutes=slot * config.TIME_STEP_MINUTES
    )


def generate_flights() -> list[list[str | None]]:
    """Build the 49 flight rows (40 clean + 9 bad) in file order."""
    rng = random.Random(config.RANDOM_SEED)
    used_ids: set[str] = set()

    clean: list[list[str]] = []
    for _ in range(config.CLEAN_FLIGHT_COUNT):
        # Size draw.
        u = rng.random()
        if u < config.SIZE_MIX[0]:
            size = "S"
        elif u < config.SIZE_MIX[1]:
            size = "M"
        else:
            size = "L"

        # Arrival draw.
        p = rng.random()
        if p < config.ARRIVAL_PEAK_SHARE:
            slot = rng.randrange(config.PEAK_FIRST_SLOT, config.PEAK_END_SLOT)
        else:
            slot = rng.randrange(0, config.OFF_PEAK_END_SLOT)
        arrival = _slot_time(slot)

        # Ground time draw.
        lo, hi = config.GROUND_MINUTES_RANGE[size]
        minutes = rng.randrange(lo, hi + config.TIME_STEP_MINUTES, config.TIME_STEP_MINUTES)
        departure = arrival + timedelta(minutes=minutes)

        # Flight ID draw.
        while True:
            code = rng.choice(config.AIRLINE_CODES)
            number = rng.randint(config.FLIGHT_NUMBER_MIN, config.FLIGHT_NUMBER_MAX)
            candidate = code + str(number)
            if candidate not in used_ids and candidate not in config.RESERVED_FLIGHT_IDS:
                used_ids.add(candidate)
                break

        clean.append(
            [
                candidate,
                size,
                format_utc(arrival),
                format_utc(departure),
            ]
        )

    clean.sort(key=lambda row: (row[2], row[0]))
    first_id = clean[0][0]

    # Fill in the duplicate bad row's flight id.
    bad_rows: list[list[str | None]] = [list(row) for row in BAD_ROWS]
    bad_rows[6][0] = first_id
    # Assert the duplicate's times differ from the original's times.
    original = next(r for r in clean if r[0] == first_id)
    assert (bad_rows[6][2], bad_rows[6][3]) != (original[2], original[3])

    # Merge: bad row k goes directly after clean row index c_k.
    result: list[list[str | None]] = []
    bad_index = {
        ((k + 1) * config.CLEAN_FLIGHT_COUNT) // (config.BAD_ROW_COUNT + 1) - 1: k
        for k in range(config.BAD_ROW_COUNT)
    }
    for i, row in enumerate(clean):
        result.append(row)
        if i in bad_index:
            result.append(bad_rows[bad_index[i]])
    return result


def write_csv(path: Path, header: list[str], rows: list[list[str | None]]) -> None:
    """Write a CSV file per section 23.15: UTF-8, LF, no BOM, trailing newline."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


def main() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(
        config.STANDS_CSV,
        ["stand_id", "stand_type", "max_size"],
        [list(s) for s in STANDS],
    )
    rows = generate_flights()
    write_csv(
        config.FLIGHTS_CSV,
        ["flight_id", "aircraft_size", "arrival_time", "departure_time"],
        rows,
    )
    logger.info("wrote %d stands and %d flight rows", len(STANDS), len(rows))


if __name__ == "__main__":
    main()

"""Loading CSV input files (sections 23.10 and 23.11).

File-level problems (missing file, bad header, size/row limits) stop the
program. Row-level problems are data and are handled by validation.py.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from stand_allocation import config


class StandsFileError(Exception):
    """Raised when stands.csv is missing, malformed, or too large."""


class FlightsFileError(Exception):
    """Raised when flights.csv is missing, malformed, or too large."""


@dataclass(frozen=True)
class RawRow:
    """One data row as read from the file, before validation."""

    line_number: int
    fields: tuple[str, ...]


def _read_records(
    path: str | Path,
    expected_header: tuple[str, ...],
    file_error: type[Exception],
) -> list[RawRow]:
    """Read and header-check a CSV file, returning its data rows."""
    path = Path(path)
    if not path.exists():
        raise file_error(f"input file not found: {path}")
    if path.stat().st_size > config.MAX_CSV_BYTES:
        raise file_error(
            f"input file {path} is {path.stat().st_size} bytes, above the "
            f"limit of {config.MAX_CSV_BYTES} bytes"
        )

    records: list[RawRow] = []
    try:
        with path.open("r", encoding=config.CSV_ENCODING, newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                raise file_error(
                    f"input file {path} is empty; expected header {', '.join(expected_header)}"
                ) from None
            if list(header) != list(expected_header):
                raise file_error(
                    f"input file {path} has header {header!r}, "
                    f"expected {', '.join(expected_header)!r}"
                )
            for record in reader:
                records.append(RawRow(line_number=reader.line_num, fields=tuple(record)))
                if len(records) > config.MAX_CSV_ROWS:
                    raise file_error(
                        f"input file {path} has more than {config.MAX_CSV_ROWS} data rows"
                    )
    except UnicodeDecodeError as exc:
        raise file_error(f"input file {path} is not valid UTF-8: {exc}") from exc
    return records


def read_flight_rows(path: Path) -> list[RawRow]:
    """Read flights.csv. Header and no rows is allowed (zero flights)."""
    return _read_records(
        path,
        ("flight_id", "aircraft_size", "arrival_time", "departure_time"),
        FlightsFileError,
    )


def load_stands(path: Path) -> list[RawRow]:
    """Read stands.csv. A header with no stand rows is an error."""
    records = _read_records(
        path,
        ("stand_id", "stand_type", "max_size"),
        StandsFileError,
    )
    if not records:
        raise StandsFileError(f"input file {path} has a header but no stand rows")
    return records

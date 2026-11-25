"""Tests for validation.py and loader.py (section 12.4)."""

from __future__ import annotations

import os
import tempfile

from stand_allocation import loader
from stand_allocation.validation import validate_rows


def _row(line_number: int, fields: tuple[str, ...]) -> loader.RawRow:
    return loader.RawRow(line_number=line_number, fields=fields)


def test_reversed_pair_logs_one_issue() -> None:
    """Row 3 of section 7.3 gives exactly one issue, DEPARTURE_BEFORE_ARRIVAL."""
    flights, issues = validate_rows(
        [_row(3, ("CZ411", "M", "2027-01-15T09:20:00Z", "2027-01-15T08:50:00Z"))]
    )
    assert flights == []
    assert len(issues) == 1
    assert issues[0].issue_code == "DEPARTURE_BEFORE_ARRIVAL"
    assert issues[0].action == "DROPPED"
    assert issues[0].field == "departure_time"


def test_offset_row_logs_one_issue() -> None:
    """Row 2 of section 7.3 gives exactly one issue, OFFSET_TIMESTAMP on arrival_time."""
    flights, issues = validate_rows(
        [_row(2, ("KT610", "S", "2027-01-15T11:40:00+05:30", "2027-01-15T07:05:00Z"))]
    )
    assert len(flights) == 1
    assert flights[0].flight_id == "KT610"
    assert len(issues) == 1
    assert issues[0].issue_code == "OFFSET_TIMESTAMP"
    assert issues[0].action == "FIXED"
    assert issues[0].field == "arrival_time"
    assert issues[0].new_value == "2027-01-15T06:10:00Z"


def test_size_format_fixed() -> None:
    """Row 1 of section 7.3: size "m" is fixed to "M"."""
    flights, issues = validate_rows(
        [_row(1, ("FR207", "m", "2027-01-15T07:15:00Z", "2027-01-15T08:40:00Z"))]
    )
    assert len(flights) == 1
    assert flights[0].aircraft_size == "M"
    assert len(issues) == 1
    assert issues[0].issue_code == "SIZE_FORMAT"
    assert issues[0].action == "FIXED"


def test_duplicate_flight_id_dropped() -> None:
    flights, issues = validate_rows(
        [
            _row(2, ("AX100", "S", "2027-01-15T06:05:00Z", "2027-01-15T07:00:00Z")),
            _row(3, ("AX100", "S", "2027-01-15T08:00:00Z", "2027-01-15T09:00:00Z")),
        ]
    )
    assert len(flights) == 1
    dropped = [i for i in issues if i.issue_code == "DUPLICATE_FLIGHT_ID"]
    assert len(dropped) == 1
    assert dropped[0].action == "DROPPED"


def test_blank_line_wrong_field_count() -> None:
    """A blank line is dropped with WRONG_FIELD_COUNT and its line number."""
    flights, issues = validate_rows([_row(5, ())])
    assert flights == []
    assert len(issues) == 1
    assert issues[0].issue_code == "WRONG_FIELD_COUNT"
    assert issues[0].row_number == 5


def test_unknown_size_dropped() -> None:
    flights, issues = validate_rows(
        [
            _row(
                2,
                (
                    "DL902",
                    "XL",
                    "2027-01-15T07:40:00Z",
                    "2027-01-15T09:10:00Z",
                ),
            )
        ]
    )
    assert flights == []
    assert len(issues) == 1
    assert issues[0].issue_code == "UNKNOWN_SIZE"


def test_ground_too_short_dropped() -> None:
    flights, issues = validate_rows(
        [
            _row(
                8,
                (
                    "BQ880",
                    "S",
                    "2027-01-15T09:00:00Z",
                    "2027-01-15T09:04:00Z",
                ),
            )
        ]
    )
    assert flights == []
    assert len(issues) == 1
    assert issues[0].issue_code == "GROUND_TOO_SHORT"


def test_bom_header_accepted() -> None:
    """A file that starts with a byte order mark loads normally."""
    header = "flight_id,aircraft_size,arrival_time,departure_time\n"
    row = "AX100,S,2027-01-15T06:05:00Z,2027-01-15T07:00:00Z\n"
    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\ufeff" + header + row)
        records = loader.read_flight_rows(path)
        assert len(records) == 1
        assert records[0].fields == ("AX100", "S", "2027-01-15T06:05:00Z", "2027-01-15T07:00:00Z")
    finally:
        os.unlink(path)

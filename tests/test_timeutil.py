"""Tests for timeutil.py (section 12.4)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stand_allocation import config
from stand_allocation.timeutil import (
    TimestampError,
    format_utc,
    parse_utc,
    seconds_from_window_start,
)


def test_round_trip_format_parse() -> None:
    original = datetime(2027, 1, 15, 6, 5, 0, tzinfo=timezone.utc)
    assert parse_utc(format_utc(original)) == original


def test_seconds_from_window_start() -> None:
    value = datetime(2027, 1, 15, 6, 5, 0, tzinfo=timezone.utc)
    assert seconds_from_window_start(value, config.WINDOW_START) == 300


def test_fractional_seconds_rejected() -> None:
    with pytest.raises(TimestampError) as exc:
        parse_utc("2027-01-15T06:05:00.5Z")
    assert exc.value.code == "FRACTIONAL_TIMESTAMP"


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(TimestampError) as exc:
        parse_utc("2027-01-15 09:00:00")
    assert exc.value.code == "NAIVE_TIMESTAMP"


def test_offset_converted_to_utc() -> None:
    value = parse_utc("2027-01-15T11:40:00+05:30")
    assert value == datetime(2027, 1, 15, 6, 10, 0, tzinfo=timezone.utc)

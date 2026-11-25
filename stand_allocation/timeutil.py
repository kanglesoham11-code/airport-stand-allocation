"""Timestamp parsing and formatting (section 23.2 and 23.3).

Python 3.10 traps: datetime.fromisoformat() accepts a trailing "Z" only from
Python 3.11, so we replace a trailing "Z" with "+00:00" before parsing.
datetime.UTC does not exist before Python 3.11, so we use timezone.utc.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone


class TimestampError(Exception):
    """Raised when a timestamp field cannot be used."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


_FRACTIONAL_RE = re.compile(r"\d{2}:\d{2}:\d{2}\.\d+")
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_utc(text: str) -> datetime:
    """Parse a UTC timestamp into a timezone-aware datetime.

    Raises TimestampError with one of: MISSING_VALUE, BAD_TIMESTAMP,
    NAIVE_TIMESTAMP, FRACTIONAL_TIMESTAMP.
    """
    stripped = text.strip()
    if stripped == "":
        raise TimestampError("MISSING_VALUE", "the timestamp field is empty")

    ends_with_z = stripped.endswith("Z") or stripped.endswith("z")
    parse_text = stripped
    if ends_with_z:
        parse_text = stripped[:-1] + "+00:00"

    # Python 3.10's fromisoformat rejects fractional seconds, so detect them
    # explicitly and report FRACTIONAL_TIMESTAMP (section 23.2, step 5).
    if _FRACTIONAL_RE.search(parse_text):
        raise TimestampError("FRACTIONAL_TIMESTAMP", "the timestamp has fractional seconds")

    try:
        value = datetime.fromisoformat(parse_text)
    except ValueError:
        # Python 3.10's fromisoformat is strict; a timezone-less datetime such
        # as "2027-01-15 09:00:00" is NAIVE_TIMESTAMP, anything else is bad.
        if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$", stripped):
            raise TimestampError("NAIVE_TIMESTAMP", "the timestamp has no time zone") from None
        raise TimestampError("BAD_TIMESTAMP", f"cannot parse timestamp {text!r}") from None

    if value.tzinfo is None:
        raise TimestampError("NAIVE_TIMESTAMP", "the timestamp has no time zone")

    if value.tzinfo is None:
        raise TimestampError("NAIVE_TIMESTAMP", "the timestamp has no time zone")

    if value.microsecond != 0:
        raise TimestampError("FRACTIONAL_TIMESTAMP", "the timestamp has fractional seconds")

    return value.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    """Format a datetime as fixed-width UTC text: YYYY-MM-DDTHH:MM:SSZ."""
    return value.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


def seconds_from_window_start(value: datetime, window_start: datetime) -> int:
    """Whole seconds from the window start to a timezone-aware UTC datetime."""
    return int((value - window_start).total_seconds())

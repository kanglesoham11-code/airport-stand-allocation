"""Tests for generate_data.py (section 12.4)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_golden_head() -> None:
    """The first five rows of data/flights.csv equal tests/golden/flights_head.csv."""
    generated = Path(ROOT, "data", "flights.csv").read_text(encoding="utf-8").splitlines()
    golden = Path(ROOT, "tests", "golden", "flights_head.csv").read_text(
        encoding="utf-8"
    ).splitlines()
    assert generated[:5] == golden

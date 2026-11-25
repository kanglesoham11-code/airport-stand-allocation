"""Tests for repository.py (section 12.4)."""

from __future__ import annotations

import re

from stand_allocation import config
from stand_allocation.db import connect
from stand_allocation.repository import latest_run


def test_run_id_format() -> None:
    """The first run is named run-0001 (section 12.4, test_repository.py)."""
    conn = connect(config.DB_PATH)
    try:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE status = 'COMPLETE' ORDER BY seq ASC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert re.fullmatch(r"run-\d{4}", row[0]), row[0]
        run = latest_run(conn)
        assert run is not None
        assert re.fullmatch(r"run-\d{4}", run.run_id)
    finally:
        conn.close()

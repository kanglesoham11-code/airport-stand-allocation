"""Tests for repository migrations (section 12.4)."""

from __future__ import annotations

from stand_allocation import config
from stand_allocation.db import connect
from stand_allocation.repository import SCHEMA_VERSION, migrate


def test_migration_reaches_schema_version_one() -> None:
    conn = connect(config.DB_PATH)
    try:
        migrate(conn)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row is not None
        assert row[0] == SCHEMA_VERSION
    finally:
        conn.close()
